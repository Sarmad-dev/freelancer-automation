from __future__ import annotations

import csv
import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.db.models_crm import Activity, Company, Contact, ImportJob, Lead
from app.db.models_email import SuppressionEntry
from app.services import csvio
from app.services.csvio import CsvProblem, parse, safe_cell, to_csv
from app.services.lead_import import resolve_mapping, suggest_mapping
from tests.conftest import add_member, make_user, second_client

HEADER = ["Name", "Email", "Company", "Website", "Industry", "Notes"]


def make_csv(rows: list[list[str]], header: list[str] | None = None, delimiter: str = ",") -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(header or HEADER)
    writer.writerows(rows)
    return out.getvalue()


def iurl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/imports{suffix}"


def preview(client: TestClient, wid: str, content: str, **extra: Any) -> dict[str, Any]:
    res = client.post(iurl(wid, "/preview"), json={"content": content, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def do_import(client: TestClient, wid: str, content: str, **extra: Any) -> dict[str, Any]:
    if "mapping" not in extra:
        extra["mapping"] = preview(client, wid, content)["suggested_mapping"]
    res = client.post(iurl(wid), json={"content": content, "filename": "leads.csv", **extra})
    assert res.status_code == 201, res.text
    return res.json()


def counts(db: DbSession, wid: str) -> tuple[int, int, int]:
    w = uuid.UUID(wid)
    return tuple(  # type: ignore[return-value]
        db.scalar(select(func.count()).select_from(m).where(m.workspace_id == w)) or 0
        for m in (Lead, Contact, Company)
    )


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return second_client(client)


class TestParsing:
    def test_bom_and_every_line_ending_are_handled(self) -> None:
        for newline in ("\r\n", "\n", "\r"):
            text = "﻿Name,Email" + newline + "Ada,ada@example.com" + newline + "Bob,bob@example.com"
            parsed = parse(text)
            assert parsed.headers == ["Name", "Email"]
            assert parsed.rows == [["Ada", "ada@example.com"], ["Bob", "bob@example.com"]]

    def test_quoted_values_may_hold_delimiters_quotes_and_newlines(self) -> None:
        text = 'Name,Notes\n"Smith, Ada","She said ""hi""\nthen left"\nBob,plain\n'
        parsed = parse(text)
        assert parsed.rows[0] == ["Smith, Ada", 'She said "hi"\nthen left']
        assert parsed.rows[1] == ["Bob", "plain"]
        assert parsed.row_numbers == [2, 4]  # line numbers count physical lines of the file

    @pytest.mark.parametrize("delimiter", [";", "\t", "|"])
    def test_other_delimiters_are_detected(self, delimiter: str) -> None:
        parsed = parse(
            make_csv([["Ada", "ada@example.com", "Acme", "", "", "x, y"]], delimiter=delimiter)
        )
        assert parsed.delimiter == delimiter and parsed.rows[0][5] == "x, y"

    def test_blank_lines_are_skipped_and_cells_are_trimmed(self) -> None:
        parsed = parse("Name,Email\n\n  Ada  , ada@example.com \n,\n   \nBob,b@example.com\n")
        assert parsed.rows == [["Ada", "ada@example.com"], ["Bob", "b@example.com"]]

    def test_short_rows_are_padded_and_long_rows_are_flagged(self) -> None:
        parsed = parse("A,B,C\n1\n1,2,3,4,5\n")
        assert parsed.rows == [["1", "", ""], ["1", "2", "3"]]
        assert parsed.extra_cells == {3: 2}

    def test_unicode_survives(self) -> None:
        assert parse("Name\n日本語 ✓ Zoë\n").rows == [["日本語 ✓ Zoë"]]

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "empty"),
            ("   \n\n", "empty"),
            ("Name,Email\n", "no data rows"),
            ("\n\n", "empty"),
            ("a\x00b,c\n1,2\n", "text CSV"),
            ("Name,name\nA,B\n", "same name"),
            ('Name\n"never closed\n', "isn't valid CSV"),
            ('Name\n"quoted"junk\n', "isn't valid CSV"),
        ],
    )
    def test_unusable_files_are_explained(self, text: str, message: str) -> None:
        with pytest.raises(CsvProblem) as exc:
            parse(text)
        assert message in str(exc.value)

    def test_size_limits_are_enforced(self) -> None:
        rows = "\n".join(f"{i}" for i in range(csvio.MAX_ROWS + 1))
        with pytest.raises(CsvProblem, match="Too many rows"):
            parse("n\n" + rows)
        assert (
            len(parse("n\n" + "\n".join(str(i) for i in range(csvio.MAX_ROWS))).rows)
            == csvio.MAX_ROWS
        )
        with pytest.raises(CsvProblem, match="Too many columns"):
            parse(",".join(f"c{i}" for i in range(csvio.MAX_COLUMNS + 1)) + "\n1\n")
        with pytest.raises(CsvProblem, match="too large"):
            parse("n\n" + "x" * (csvio.MAX_CHARS + 1))

    def test_an_oversized_single_cell_is_reported_not_a_crash(self) -> None:
        with pytest.raises(CsvProblem):
            parse('n\n"' + "x" * 200_000 + '"\n')


class TestWriting:
    @pytest.mark.parametrize(
        "value", ["=1+1", "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1)", "\t=1", "\r=1"]
    )
    def test_formula_prefixes_are_neutralised(self, value: str) -> None:
        assert safe_cell(value) == "'" + value

    @pytest.mark.parametrize(
        "value", ["plain", "", "a=b", "x+y", "+1 (555) 010-0100", "+44 20 7946 0000", "日本語"]
    )
    def test_ordinary_values_and_phone_numbers_are_left_alone(self, value: str) -> None:
        assert safe_cell(value) == value

    def test_output_is_valid_csv_with_a_bom_for_spreadsheet_apps(self) -> None:
        text = to_csv(["a", "b"], [['x,"y"', "line\nbreak"]])
        assert text.startswith("﻿")
        assert list(csv.reader(io.StringIO(text.lstrip("﻿")))) == [
            ["a", "b"],
            ['x,"y"', "line\nbreak"],
        ]


class TestMapping:
    def test_headers_are_matched_to_fields_by_common_names(self) -> None:
        m = suggest_mapping(
            ["Full Name", "E-mail", "Organization", "Job Title", "Site", "Tags", "Weird"]
        )
        assert (
            m["name"] == "Full Name" and m["email"] == "E-mail" and m["company"] == "Organization"
        )
        assert m["role"] == "Job Title" and m["website"] == "Site" and m["tags"] == "Tags"
        assert m["notes"] is None

    def test_a_column_is_suggested_for_at_most_one_field(self) -> None:
        m = suggest_mapping(["Title", "Email"])
        assert list(m.values()).count("Title") == 1

    def test_mapping_problems_are_reported(self) -> None:
        headers = ["Name", "Email", "Other"]
        assert (
            resolve_mapping({"name": "Nope"}, headers)[1] == "The column “Nope” isn't in the file."
        )
        assert "more than one field" in (
            resolve_mapping({"name": "Name", "email": "Name"}, headers)[1] or ""
        )
        assert "at least one of name, email or company" in (
            resolve_mapping({"notes": "Other"}, headers)[1] or ""
        )
        ok, problem = resolve_mapping({"name": " name ", "email": "EMAIL"}, headers)
        assert problem is None and ok == {"name": 0, "email": 1}


class TestPreview:
    def test_a_preview_changes_nothing(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv([["Ada", "ada@example.com", "Acme", "acme.example", "SaaS", "hi"]])
        before = counts(db, wid)
        p = preview(client, wid, content)
        assert p["counts"] == {"create": 1, "update": 0, "skip_duplicate": 0, "error": 0}
        assert counts(db, wid) == before == (0, 0, 0)
        assert (
            db.scalar(
                select(func.count())
                .select_from(ImportJob)
                .where(ImportJob.workspace_id == uuid.UUID(wid))
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Activity)
                .where(Activity.workspace_id == uuid.UUID(wid))
            )
            == 0
        )

    def test_the_preview_describes_each_row_and_suggests_a_mapping(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv(
            [
                ["Ada", "ada@example.com", "Acme", "acme.example", "SaaS", "n"],
                ["Bob", "not-an-email", "Bolt", "", "", ""],
            ]
        )
        p = preview(client, wid, content)
        assert p["delimiter"] == "," and p["headers"] == HEADER and p["total_rows"] == 2
        assert p["suggested_mapping"]["email"] == "Email" and p["mapping"] == p["suggested_mapping"]
        assert [r["action"] for r in p["rows"]] == ["create", "error"]
        assert p["rows"][0]["values"]["company"] == "Acme"
        assert p["rows"][1]["issues"] == ["Enter a valid email address."]
        assert p["errors"] == [
            {
                "row": 3,
                "column": "Email",
                "message": "Enter a valid email address.",
                "value": "not-an-email",
                "kind": "error",
            }
        ]

    def test_an_incomplete_mapping_is_explained_not_an_error(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv([["Ada", "a@example.com", "", "", "", ""]])
        p = preview(client, wid, content, mapping={"notes": "Notes"})
        assert p["mapping_problem"] and p["rows"] == [] and p["counts"]["create"] == 0

    @pytest.mark.parametrize(
        ("content", "fragment"),
        [("", "empty"), ("Name,Email\n", "no data rows"), ("a\x00\n1\n", "text csv")],
    )
    def test_unusable_files_get_a_clear_422(
        self, client: TestClient, content: str, fragment: str
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(iurl(wid, "/preview"), json={"content": content or " "})
        assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_csv"
        assert fragment in res.json()["error"]["message"].lower()

    def test_the_preview_and_the_import_agree(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        do_import(client, wid, make_csv([["Old", "old@example.com", "Acme", "", "", ""]]))
        content = make_csv(
            [
                ["New", "new@example.com", "Acme", "", "", ""],
                ["Old Again", "OLD@example.com", "", "", "", ""],
                ["Bad", "x", "", "", "", ""],
                ["", "", "", "", "", ""],
                ["Twin", "new@example.com", "", "", "", ""],
            ]
        )
        p = preview(client, wid, content)
        job = do_import(client, wid, content)
        assert (job["created_count"], job["updated_count"], job["skipped_count"], job["error_count"]) == (
            p["counts"]["create"], p["counts"]["update"], p["counts"]["skip_duplicate"], p["counts"]["error"],
        )  # fmt: skip
        assert (p["counts"]["create"], p["counts"]["skip_duplicate"], p["counts"]["error"]) == (
            1,
            2,
            1,
        )

    def test_only_the_first_rows_are_listed_but_all_are_counted(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        rows = [[f"P{i}", f"p{i}@example.com", "", "", "", ""] for i in range(60)]
        p = preview(client, wid, make_csv(rows))
        assert p["total_rows"] == 60 and len(p["rows"]) == 25 and p["counts"]["create"] == 60

    def test_do_not_contact_addresses_are_flagged_before_import(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        db.add(
            SuppressionEntry(
                workspace_id=uuid.UUID(wid),
                email_normalized="stop@example.com",
                reason="unsubscribe",
            )
        )
        db.commit()
        p = preview(client, wid, make_csv([["Stop", "STOP@example.com", "", "", "", ""]]))
        assert p["suppressed"] == 1 and "do-not-contact" in p["rows"][0]["warnings"][0]
        assert p["rows"][0]["action"] == "create"  # it is their data; it just can never be emailed


class TestRowValidation:
    @pytest.mark.parametrize(
        ("row", "column", "fragment"),
        [
            (["x", "bad", "", "", "", ""], "Email", "valid email"),
            (["x", "", "", "javascript:alert(1)", "", ""], "Website", "public website"),
            (["x", "", "", "http://localhost", "", ""], "Website", "public"),
            (["x", "", "", "", "i" * 101, ""], "Industry", "at most 100"),
            (["n" * 201, "", "", "", "", ""], "Name", "at most 200"),
            (["x", "", "", "", "", "z" * 4001], "Notes", "at most 4000"),
            (["a\x01b", "", "", "", "", ""], "Name", "invalid characters"),
        ],
    )
    def test_each_problem_is_reported_against_its_column(
        self, client: TestClient, row: list[str], column: str, fragment: str
    ) -> None:
        wid = make_user(client)["workspace_id"]
        p = preview(client, wid, make_csv([row]))
        assert p["counts"]["error"] == 1 and p["counts"]["create"] == 0
        assert p["errors"][0]["column"] == column and fragment in p["errors"][0]["message"]

    def test_a_row_needs_a_name_an_email_or_a_company(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        p = preview(client, wid, make_csv([["", "", "", "acme.example", "SaaS", "only extras"]]))
        assert p["counts"]["error"] == 1 and "at least a name" in p["errors"][0]["message"]

    def test_extra_values_are_an_error_not_silent_data_corruption(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        p = preview(
            client, wid, "Name,Email\nAda,ada@example.com\nBob Smith, Jr,bob@example.com,extra\n"
        )
        assert [r["action"] for r in p["rows"]] == ["create", "error"]
        assert any("more value" in e["message"] for e in p["errors"])

    def test_specific_fields_have_their_own_rules(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        header = ["Name", "Size", "Budget", "Status", "Phone", "Tags"]
        rows = [
            ["a", "11–50", "HIGH", "Qualified", "+1 (555) 010-0100", "x; y | z, w"],
            ["b", "huge", "", "", "", ""],
            ["c", "", "lots", "", "", ""],
            ["d", "", "", "maybe", "", ""],
            ["e", "", "", "", "call me", ""],
            ["f", "", "", "", "", ";".join(f"t{i}" for i in range(11))],
            ["g", "", "", "", "", "x" * 51],
        ]
        p = preview(client, wid, make_csv(rows, header))
        assert [r["action"] for r in p["rows"]] == ["create"] + ["error"] * 6
        ok = p["rows"][0]["values"]
        assert (
            ok["company_size"] == "11-50" and ok["budget"] == "high" and ok["status"] == "qualified"
        )
        assert ok["tags"] == "x, y, z, w"

    def test_markup_and_formulas_in_cells_are_kept_as_text(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv(
            [["<script>alert(1)</script>", "e@example.com", "=HYPERLINK(1)", "", "", "{{7*7}}"]]
        )
        do_import(client, wid, content)
        row = db.scalar(select(Contact).where(Contact.workspace_id == uuid.UUID(wid)))
        assert row is not None and row.full_name == "<script>alert(1)</script>"


class TestImport:
    def test_rows_become_linked_leads_contacts_and_companies_with_provenance(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv(
            [
                [
                    "Ada",
                    "ada@acme.example",
                    "Acme",
                    "https://www.acme.example",
                    "SaaS",
                    "Needs web development",
                ],
                ["Bob", "bob@acme.example", "ACME", "", "", ""],
                ["Cy", "", "Cyber Co", "", "", ""],
            ]
        )
        job = do_import(client, wid, content)
        assert job["status"] == "completed" and job["total_rows"] == 3 and job["created_count"] == 3
        leads = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"]
        assert len(leads) == 3
        companies = client.get(f"/api/v1/workspaces/{wid}/companies").json()["items"]
        assert sorted(c["name"] for c in companies) == [
            "Acme",
            "Cyber Co",
        ]  # ACME matched Acme by name
        acme = next(c for c in companies if c["name"] == "Acme")
        assert (
            acme["contact_count"] == 2
            and acme["lead_count"] == 2
            and acme["domain"] == "acme.example"
        )
        ada = next(x for x in leads if x["contact"] and x["contact"]["full_name"] == "Ada")
        assert ada["source"] == "CSV import" and ada["source_retrieved_at"]
        assert ada["company"]["name"] == "Acme" and ada["stage"]["key"] == "new"
        assert ada["fit_band"] is not None  # scored on import
        assert ada["title"] == "Acme – Ada"
        w = uuid.UUID(wid)
        contact = db.scalar(
            select(Contact).where(Contact.workspace_id == w, Contact.full_name == "Ada")
        )
        assert (
            contact is not None
            and contact.source == "CSV import"
            and contact.source_retrieved_at is not None
        )
        assert acme["source"] == "CSV import" and acme["source_retrieved_at"]
        assert all(x["is_sample"] is False for x in leads)

    def test_a_source_column_overrides_the_default_label(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv(
            [["Ada", "a@example.com", "", "", "", "", "Conference list"]], HEADER + ["Source"]
        )
        do_import(client, wid, content)
        assert (
            client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]["source"]
            == "Conference list"
        )

    def test_each_imported_lead_has_a_timeline_entry_pointing_at_the_import(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        job = do_import(client, wid, make_csv([["Ada", "a@example.com", "", "", "", ""]]))
        lead = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]
        items = client.get(f"/api/v1/workspaces/{wid}/leads/{lead['id']}/activities").json()[
            "items"
        ]
        entry = next(i for i in items if i["summary"] == "Imported from CSV")
        assert entry["details"]["import_id"] == job["id"] and entry["details"]["row"] == 2

    def test_valid_rows_are_saved_and_problem_rows_are_reported(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv(
            [
                ["Good", "good@example.com", "", "", "", ""],
                ["Bad", "bad", "", "", "", ""],
                ["Fine", "fine@example.com", "", "", "", ""],
            ]
        )
        job = do_import(client, wid, content)
        assert (job["created_count"], job["error_count"]) == (2, 1)
        assert counts(db, wid)[0] == 2

    def test_tags_are_created_and_reused_case_insensitively(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.post(f"/api/v1/workspaces/{wid}/tags", json={"name": "Warm"})
        content = make_csv(
            [
                ["A", "a@example.com", "", "", "", "", "warm; Hot"],
                ["B", "b@example.com", "", "", "", "", "HOT"],
            ],
            HEADER + ["Tags"],
        )
        do_import(client, wid, content)
        tags = client.get(f"/api/v1/workspaces/{wid}/tags").json()["items"]
        assert sorted(t["name"] for t in tags) == ["Hot", "Warm"]
        leads = {
            x["contact"]["full_name"]: x
            for x in client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"]
        }
        assert sorted(t["name"] for t in leads["A"]["tags"]) == ["Hot", "Warm"]
        assert [t["name"] for t in leads["B"]["tags"]] == ["Hot"]

    def test_name_only_and_company_only_rows_are_importable(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        do_import(
            client,
            wid,
            make_csv([["Only Name", "", "", "", "", ""], ["", "", "Only Co", "", "", ""]]),
        )
        titles = sorted(
            x["title"] for x in client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"]
        )
        assert titles == ["Only Co", "Only Name"]

    def test_do_not_contact_rows_are_imported_and_flagged(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        db.add(
            SuppressionEntry(
                workspace_id=uuid.UUID(wid),
                email_normalized="stop@example.com",
                reason="unsubscribe",
            )
        )
        db.commit()
        job = do_import(client, wid, make_csv([["Stop", "stop@example.com", "", "", "", ""]]))
        assert job["suppressed"] == 1
        assert (
            client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]["do_not_contact"]
            is True
        )

    def test_leads_are_scored_with_the_workspaces_current_criteria(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(
            f"/api/v1/workspaces/{wid}/profile",
            json={"services": ["Web development"], "industries": ["SaaS"]},
        )
        do_import(
            client,
            wid,
            make_csv([["A", "a@example.com", "Acme", "", "SaaS", "web development needed"]]),
        )
        lead = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]
        assert lead["fit_band"] == "strong"

    def test_importing_the_same_file_twice_adds_nothing(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv(
            [["Ada", "a@example.com", "Acme", "", "", ""], ["", "", "NoEmail Co", "", "", ""]]
        )
        do_import(client, wid, content)
        before = counts(db, wid)
        second = do_import(client, wid, content)
        assert (second["created_count"], second["skipped_count"]) == (0, 2)
        assert counts(db, wid) == before

    def test_a_large_file_imports_completely(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        rows = [
            [
                f"Person {i}",
                f"p{i}@co{i % 50}.example",
                f"Company {i % 50}",
                f"co{i % 50}.example",
                "SaaS",
                "",
            ]
            for i in range(600)
        ]
        job = do_import(client, wid, make_csv(rows))
        assert job["created_count"] == 600
        leads, contacts, companies = counts(db, wid)
        assert (leads, contacts, companies) == (600, 600, 50)

    def test_too_many_rows_are_refused_before_anything_is_saved(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        body = "Name\n" + "\n".join(f"P{i}" for i in range(csvio.MAX_ROWS + 1))
        res = client.post(iurl(wid), json={"content": body, "mapping": {"name": "Name"}})
        assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_csv"
        assert counts(db, wid) == (0, 0, 0)

    def test_the_mapping_is_validated(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv([["Ada", "a@example.com", "", "", "", ""]])
        for mapping in ({"name": "Missing"}, {"notes": "Notes"}, {"name": "Name", "email": "Name"}):
            res = client.post(iurl(wid), json={"content": content, "mapping": mapping})
            assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_mapping", (
                mapping
            )

    @pytest.mark.parametrize(
        "extra",
        [
            {"duplicate_strategy": "overwrite_everything"},
            {"workspace_id": str(uuid.uuid4())},
            {"is_sample": True},
            {"filename": ""},
        ],
    )
    def test_malformed_requests_are_rejected(
        self, client: TestClient, extra: dict[str, Any]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv([["Ada", "a@example.com", "", "", "", ""]])
        res = client.post(
            iurl(wid), json={"content": content, "mapping": {"name": "Name"}, **extra}
        )
        assert res.status_code == 422

    def test_the_import_is_recorded_and_audited_with_counts_only(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        job = do_import(
            client,
            wid,
            make_csv([["Secret Person", "secret@example.com", "Secret Co", "", "", ""]]),
        )
        history = client.get(iurl(wid)).json()
        assert history["total"] == 1 and history["items"][0]["id"] == job["id"]
        assert client.get(iurl(wid, f"/{job['id']}")).json()["filename"] == "leads.csv"
        event = db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "leads.imported", AuditEvent.workspace_id == uuid.UUID(wid)
            )
        ).one()
        assert event.details == {
            "created": 1,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "strategy": "skip",
        }
        stored = db.get(ImportJob, uuid.UUID(job["id"]))
        assert stored is not None and "secret@example.com" not in str(stored.mapping) + str(
            stored.errors
        )


class TestDuplicates:
    def seed(self, client: TestClient, wid: str) -> None:
        do_import(
            client,
            wid,
            make_csv(
                [["Ada Old", "ada@example.com", "Acme", "acme.example", "Retail", "old notes"]]
            ),
        )

    def test_skip_leaves_existing_records_untouched(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        self.seed(client, wid)
        job = do_import(
            client, wid, make_csv([["Ada New", "ADA@example.com", "Acme", "", "SaaS", "new notes"]])
        )
        assert (job["created_count"], job["skipped_count"]) == (0, 1)
        lead = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]
        assert (
            lead["contact"]["full_name"] == "Ada Old"
            and lead["industry"] == "Retail"
            and lead["notes"] == "old notes"
        )

    def test_update_fills_in_the_existing_records(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        self.seed(client, wid)
        content = make_csv([["Ada New", "ADA@example.com", "Acme", "", "SaaS", "new notes"]])
        job = do_import(client, wid, content, duplicate_strategy="update")
        assert (job["created_count"], job["updated_count"], job["skipped_count"]) == (0, 1, 0)
        leads = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"]
        assert len(leads) == 1
        lead = leads[0]
        assert (
            lead["contact"]["full_name"] == "Ada New"
            and lead["industry"] == "SaaS"
            and lead["notes"] == "new notes"
        )
        timeline = client.get(f"/api/v1/workspaces/{wid}/leads/{lead['id']}/activities").json()[
            "items"
        ]
        assert "Updated by CSV import" in [t["summary"] for t in timeline]

    def test_update_never_blanks_a_field_with_an_empty_cell(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        self.seed(client, wid)
        do_import(
            client,
            wid,
            make_csv([["", "ada@example.com", "", "", "", ""]]),
            duplicate_strategy="update",
        )
        lead = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]
        assert (
            lead["contact"]["full_name"] == "Ada Old"
            and lead["industry"] == "Retail"
            and lead["notes"] == "old notes"
        )

    def test_update_can_move_a_lead_forward_and_adds_tags_without_removing_any(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        header = [*HEADER, "Status", "Tags"]
        do_import(
            client,
            wid,
            make_csv([["Ada", "ada@example.com", "", "", "", "", "new", "one"]], header),
        )
        do_import(
            client,
            wid,
            make_csv([["Ada", "ada@example.com", "", "", "", "", "qualified", "two"]], header),
            duplicate_strategy="update",
        )
        lead = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]
        assert lead["status"] == "qualified" and lead["stage"]["key"] == "qualified"
        assert sorted(t["name"] for t in lead["tags"]) == ["one", "two"]

    def test_duplicates_inside_one_file(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        rows = [
            ["Ada", "ada@example.com", "", "", "", "first"],
            ["Ada Again", "ADA@example.com", "", "", "", "second"],
        ]
        skipped = do_import(client, wid, make_csv(rows))
        assert (skipped["created_count"], skipped["skipped_count"]) == (1, 1)
        assert client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"][0]["notes"] == "first"

    def test_within_file_duplicates_merge_under_update(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        rows = [
            ["Ada", "ada@example.com", "", "", "", "first"],
            ["Ada Again", "ADA@example.com", "", "", "", "second"],
        ]
        job = do_import(client, wid, make_csv(rows), duplicate_strategy="update")
        assert (job["created_count"], job["updated_count"]) == (1, 1)
        leads = client.get(f"/api/v1/workspaces/{wid}/leads").json()["items"]
        assert len(leads) == 1 and leads[0]["notes"] == "second"

    def test_rows_without_an_email_match_on_title_and_company(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        header = [*HEADER, "Lead"]
        first = make_csv([["", "", "Acme", "", "", "", "Website rebuild"]], header)
        do_import(client, wid, first)
        again = do_import(client, wid, first)
        assert again["skipped_count"] == 1
        different = do_import(
            client, wid, make_csv([["", "", "Acme", "", "", "", "Brand refresh"]], header)
        )
        assert different["created_count"] == 1
        other_company = do_import(
            client, wid, make_csv([["", "", "Bolt", "", "", "", "Website rebuild"]], header)
        )
        assert other_company["created_count"] == 1

    def test_two_people_at_one_company_are_not_duplicates(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        job = do_import(
            client,
            wid,
            make_csv([["Ada", "", "Acme", "", "", ""], ["Bob", "", "Acme", "", "", ""]]),
        )
        assert job["created_count"] == 2

    def test_the_same_company_name_with_a_different_website_is_a_different_company(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        do_import(
            client,
            wid,
            make_csv(
                [
                    ["A", "a@one.example", "Nova", "one.example", "", ""],
                    ["B", "b@two.example", "Nova", "two.example", "", ""],
                ]
            ),
        )
        companies = client.get(f"/api/v1/workspaces/{wid}/companies").json()
        assert companies["total"] == 2

    def test_a_known_contact_without_a_lead_gets_one_under_update(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.post(
            f"/api/v1/workspaces/{wid}/contacts",
            json={"full_name": "Ada", "email": "ada@example.com"},
        )
        job = do_import(
            client,
            wid,
            make_csv([["Ada", "ada@example.com", "Acme", "", "", ""]]),
            duplicate_strategy="update",
        )
        assert job["updated_count"] == 1
        assert client.get(f"/api/v1/workspaces/{wid}/leads").json()["total"] == 1

    def test_the_same_email_in_two_workspaces_is_not_a_duplicate(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        content = make_csv([["Ada", "ada@example.com", "Acme", "acme.example", "", ""]])
        do_import(client, a["workspace_id"], content)
        job = do_import(other, b["workspace_id"], content)
        assert job["created_count"] == 1 and job["skipped_count"] == 0


class TestErrorReport:
    def test_the_report_lists_errors_and_skipped_duplicates(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        content = make_csv(
            [
                ["Ada", "ada@example.com", "", "", "", ""],
                ["Bad", "bad-email", "", "", "", ""],
                ["Ada Dup", "ada@example.com", "", "", "", ""],
            ]
        )
        job = do_import(client, wid, content)
        res = client.get(iurl(wid, f"/{job['id']}/errors.csv"))
        assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
        assert (
            "attachment" in res.headers["content-disposition"]
            and res.headers["cache-control"] == "no-store"
        )
        rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿"))))
        assert rows[0] == ["row", "type", "column", "problem", "value"]
        assert rows[1][:3] == ["3", "error", "Email"] and rows[1][4] == "bad-email"
        assert rows[2][:2] == ["4", "skipped"]

    def test_report_cells_cannot_become_spreadsheet_formulas(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        header = ["Name", "Email"]
        job = do_import(client, wid, make_csv([["x", '=HYPERLINK("http://evil.example")']], header))
        rows = list(
            csv.reader(
                io.StringIO(client.get(iurl(wid, f"/{job['id']}/errors.csv")).text.lstrip("﻿"))
            )
        )
        assert rows[1][4].startswith("'=")

    def test_the_stored_error_list_is_capped(
        self, client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        monkeypatch.setattr("app.services.lead_import.MAX_STORED_ERRORS", 3)
        rows = [[f"P{i}", "nope", "", "", "", ""] for i in range(6)]
        job = do_import(client, wid, make_csv(rows))
        assert job["error_count"] == 6 and job["errors_truncated"] is True
        stored = db.get(ImportJob, uuid.UUID(job["id"]))
        assert stored is not None and len(stored.errors) == 3

    def test_reports_are_private_to_the_workspace_and_the_owner(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        a, b = make_user(client), make_user(other)
        job = do_import(client, a["workspace_id"], make_csv([["Bad", "nope", "", "", "", ""]]))
        url = iurl(a["workspace_id"], f"/{job['id']}/errors.csv")
        assert other.get(url).status_code == 404
        assert other.get(iurl(b["workspace_id"], f"/{job['id']}/errors.csv")).status_code == 404
        add_member(db, a["workspace_id"], b["me"]["user"]["id"])
        assert other.get(url).status_code == 403
        client.cookies.clear()
        assert client.get(url).status_code == 401


class TestPermissions:
    def test_only_the_owner_can_preview_or_import(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        owner, member = make_user(client), make_user(other)
        wid = owner["workspace_id"]
        add_member(db, wid, member["me"]["user"]["id"])
        content = make_csv([["Ada", "a@example.com", "", "", "", ""]])
        assert other.post(iurl(wid, "/preview"), json={"content": content}).status_code == 403
        res = other.post(iurl(wid), json={"content": content, "mapping": {"name": "Name"}})
        assert res.status_code == 403
        assert counts(db, wid) == (0, 0, 0)
        assert other.get(iurl(wid)).status_code == 200  # history is readable

    def test_other_workspaces_are_unreachable(self, client: TestClient, other: TestClient) -> None:
        a = make_user(client)
        make_user(other)
        content = make_csv([["Ada", "a@example.com", "", "", "", ""]])
        assert (
            other.post(iurl(a["workspace_id"], "/preview"), json={"content": content}).status_code
            == 404
        )
        assert (
            other.post(
                iurl(a["workspace_id"]), json={"content": content, "mapping": {"name": "Name"}}
            ).status_code
            == 404
        )
        job = do_import(client, a["workspace_id"], content)
        assert other.get(iurl(a["workspace_id"], f"/{job['id']}")).status_code == 404

    def test_unauthenticated_requests_are_refused(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.cookies.clear()
        assert client.post(iurl(wid, "/preview"), json={"content": "a\n1"}).status_code == 401
        assert client.get(iurl(wid)).status_code == 401
