"""Development seed data: ONE fictional freelancer with clearly fictional companies and contacts.

Safety:
- Refuses to run outside ``development``/``test`` (see ``app.cli``); the demo password below is public.
- Every company/contact/domain uses reserved ``.example`` names (RFC 2606) so nothing can reach a real
  person, and every record that has an ``is_sample`` column sets it to true.
- Idempotent: if the demo user already exists nothing is changed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models import (
    FreelancerProfile,
    Membership,
    OnboardingProgress,
    User,
    Workspace,
)
from app.db.models_crm import (
    Activity,
    Company,
    Contact,
    FitScoringConfig,
    ImportJob,
    KnowledgeItem,
    KnowledgeItemVersion,
    Lead,
    LeadTag,
    Opportunity,
    Tag,
    Task,
)
from app.db.models_email import (
    Conversation,
    Draft,
    EmailAccount,
    IntegrationConnection,
    Message,
    SuppressionEntry,
)
from app.db.models_workflow import (
    ApprovalRequest,
    Notification,
    UsageRecord,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowRun,
    WorkflowStepRun,
    WorkflowVersion,
)
from app.security.passwords import hash_password
from app.services.fit_scoring import DEFAULT_CRITERIA, ProfileFacts, Scorer
from app.services.pipeline import ensure_default_stages
from app.services.workflows import definition_checksum

DEMO_EMAIL = "demo@freelancer-os.example"
# Development only (the seed refuses to run in production). Public by design.
DEMO_PASSWORD = "demo passphrase 2026"


def seed_demo(db: DbSession) -> tuple[bool, uuid.UUID | None]:
    """Create the demo account and sample data. Returns (created, workspace_id)."""
    existing = db.scalar(select(User).where(User.email_normalized == DEMO_EMAIL))
    if existing is not None:
        existing_workspace_id = db.scalar(
            select(Membership.workspace_id).where(Membership.user_id == existing.id)
        )
        return False, existing_workspace_id

    now = utcnow()
    user = User(
        email=DEMO_EMAIL,
        email_normalized=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD),
        display_name="Alex Rivera (demo)",
        last_sign_in_at=None,
    )
    db.add(user)
    db.flush()
    ws = Workspace(
        name="Alex Rivera's demo workspace",
        kind="personal",
        timezone="Europe/Berlin",
        demo_mode=True,
    )
    db.add(ws)
    db.flush()
    wid = ws.id
    db.add(Membership(workspace_id=wid, user_id=user.id, role="owner"))
    db.add(
        OnboardingProgress(
            workspace_id=wid,
            status="completed",
            current_step="goal",
            completed_at=now,
            completed_steps=[
                "role",
                "services",
                "skills",
                "target_clients",
                "industries",
                "portfolio",
                "experience",
                "tone",
                "timezone",
                "goal",
            ],
        )
    )
    profile = FreelancerProfile(
        workspace_id=wid,
        role_title="Independent web developer (fictional)",
        summary="Fictional demo persona. Builds fast, accessible marketing sites and small web apps.",
        services=["Web development", "Performance audits", "Accessibility reviews"],
        skills=["TypeScript", "React", "PostgreSQL", "Accessibility"],
        target_clients="Seed-stage SaaS teams who need a reliable front-end partner.",
        industries=["SaaS", "Fintech"],
        portfolio_urls=["https://portfolio.alex-rivera.example/work"],
        years_experience=8,
        experience_summary="Fictional experience for demonstration only.",
        tone="friendly",
        business_goal="find_new_clients",
        differentiators=[
            "Fixed-scope audits (fictional)",
            "Accessibility-first builds (fictional)",
        ],
        excluded_customers=["Gambling operators", "Anyone needing a rush job under one week"],
        pricing_guidance="Fictional: quote after a discovery call; never state a number in a first email.",
        preferred_cta="Book a 20-minute intro call (fictional)",
        version=1,
    )
    db.add(profile)
    stages = {s.key: s for s in ensure_default_stages(db, wid)}

    # --- knowledge: one item per lifecycle state, each with a v1 history snapshot -----------------------
    for kind, title, content, status, source, enabled in (
        (
            "service",
            "Performance audits",
            "Fictional: fixed-scope audits delivered in one week.",
            "approved",
            "manual",
            True,
        ),
        (
            "fact",
            "Accessibility focus",
            "Fictional: all builds target WCAG 2.2 AA.",
            "approved",
            "manual",
            True,
        ),
        (
            "fact",
            "Retired offering",
            "Fictional: legacy WordPress maintenance (no longer offered).",
            "approved",
            "manual",
            False,
        ),
        (
            "case_study",
            "Case study (unreviewed)",
            "Fictional draft extracted from a pasted document. Not verified.",
            "pending_review",
            "extracted",
            True,
        ),
        (
            "fact",
            "Work in progress",
            "Fictional note the freelancer has not finished writing.",
            "draft",
            "manual",
            True,
        ),
        (
            "fact",
            "Rejected claim",
            "Fictional claim the freelancer decided not to use.",
            "rejected",
            "extracted",
            True,
        ),
    ):
        approved = status == "approved"
        item = KnowledgeItem(
            workspace_id=wid,
            kind=kind,
            title=title,
            content=content,
            source_type=source,
            source_ref="Demo resume.pdf (fictional)" if source == "extracted" else None,
            status=status,
            is_enabled=enabled,
            approved_at=now if approved else None,
            approved_by_user_id=user.id if approved else None,
            created_by_user_id=user.id,
        )
        db.add(item)
        db.flush()
        db.add(
            KnowledgeItemVersion(
                workspace_id=wid,
                item_id=item.id,
                version=1,
                kind=kind,
                title=title,
                content=content,
                source_ref=item.source_ref,
                changed_by_user_id=user.id,
            )
        )

    # --- companies & contacts (all .example) --------------------------------------------------
    companies: dict[str, Company] = {}
    for key, name, industry, size, place in (
        ("northwind", "Northwind Studio (fictional)", "Design", "11-50", "Berlin, Germany"),
        ("fabrikam", "Fabrikam Labs (fictional)", "SaaS", "11-50", "Remote (US)"),
        ("contoso", "Contoso Works (fictional)", "Fintech", "201-1000", "London, UK"),
        ("tailspin", "Tailspin Co (fictional)", "Gambling", "2-10", None),
    ):
        c = Company(
            workspace_id=wid,
            name=name,
            domain=f"{key}.example",
            domain_normalized=f"{key}.example",
            website=f"https://{key}.example",
            industry=industry,
            size_label=size,
            location=place,
            source="seed",
            source_retrieved_at=now,
            is_sample=True,
        )
        db.add(c)
        companies[key] = c
    db.flush()
    contacts: dict[str, Contact] = {}
    for key, full_name, role in (
        ("northwind", "Jordan Lee (fictional)", "Head of Product"),
        ("fabrikam", "Sam Patel (fictional)", "CTO"),
        ("contoso", "Riley Chen (fictional)", "Engineering Manager"),
        ("tailspin", "Morgan Diaz (fictional)", "Founder"),
    ):
        first = full_name.split()[0].lower()
        email = f"{first}@{key}.example"
        ct = Contact(
            workspace_id=wid,
            company_id=companies[key].id,
            full_name=full_name,
            email=email,
            email_normalized=email,
            role_title=role,
            source="seed",
            is_sample=True,
        )
        db.add(ct)
        contacts[key] = ct
    db.flush()

    # --- tags, leads ---------------------------------------------------------------------------
    tags = {
        n: Tag(workspace_id=wid, name=n, name_normalized=n.casefold(), color=c)
        for n, c in (("Priority", "#A8E66B"), ("SaaS", "#60A5FA"), ("Warm intro", "#FBBF24"))
    }
    db.add_all(tags.values())
    db.flush()
    leads: dict[str, Lead] = {}
    criteria = [dict(c) for c in DEFAULT_CRITERIA]
    by_key = {c["key"]: c for c in criteria}
    by_key["service_match"]["keywords"] = ["website", "front-end", "landing page"]
    by_key["geography"]["preferred"] = ["Remote", "Germany", "UK"]
    by_key["company_size"]["preferred"] = ["2-10", "11-50", "51-200"]
    db.add(
        FitScoringConfig(workspace_id=wid, version=1, criteria=criteria, updated_by_user_id=user.id)
    )
    scorer = Scorer(
        ProfileFacts(
            services=tuple(profile.services),
            skills=tuple(profile.skills),
            industries=tuple(profile.industries),
            excluded_customers=tuple(profile.excluded_customers),
            version=profile.version,
        ),
        criteria,
        1,
    )
    for key, status, stage, notes, budget in (
        (
            "northwind",
            "replied",
            "replied",
            "Fictional: needs a front-end rebuild and an accessibility audit for their marketing site.",
            "high",
        ),
        (
            "fabrikam",
            "qualified",
            "qualified",
            "Fictional: seed-stage SaaS team with an accessibility requirement; web development help wanted.",
            "medium",
        ),
        (
            "contoso",
            "contacted",
            "contacted",
            "Fictional: exploring a website refresh. Budget unknown.",
            None,
        ),
        (
            "tailspin",
            "new",
            "new",
            "Fictional: online gambling operator wants a new landing page.",
            "low",
        ),
    ):
        ld = Lead(
            workspace_id=wid,
            company_id=companies[key].id,
            contact_id=contacts[key].id,
            stage_id=stages[stage].id,
            title=f"{companies[key].name} website rebuild",
            status=status,
            source="seed",
            source_retrieved_at=now,
            industry=companies[key].industry,
            location=companies[key].location,
            notes=notes,
            budget_signal=budget,
            next_action="Follow up",
            next_action_at=now + timedelta(days=2),
            last_activity_at=now,
            owner_user_id=user.id,
            is_sample=True,
        )
        scorer.apply(ld, companies[key])
        db.add(ld)
        leads[key] = ld
    inbound = Lead(
        workspace_id=wid,
        stage_id=stages["new"].id,
        title="Inbound inquiry (fictional)",
        status="new",
        source="seed",
        source_retrieved_at=now,
        owner_user_id=user.id,
        last_activity_at=now,
        is_sample=True,
    )
    scorer.apply(inbound, None)  # almost nothing is known, so no score is given
    db.add(inbound)
    leads["inbound"] = inbound
    db.flush()
    for ld in leads.values():
        db.add(
            Activity(
                workspace_id=wid,
                lead_id=ld.id,
                actor_user_id=None,
                kind="system",
                summary="Lead created (sample data)",
                occurred_at=now - timedelta(days=3),
            )
        )
    db.add(
        ImportJob(
            workspace_id=wid,
            filename="sample-leads.csv (demo)",
            duplicate_strategy="skip",
            mapping={"name": "Name", "email": "Email", "company": "Company"},
            total_rows=6,
            created_count=4,
            updated_count=0,
            skipped_count=1,
            error_count=1,
            errors=[
                {
                    "row": 4,
                    "column": "Email",
                    "message": "Enter a valid email address.",
                    "value": "not-an-email",
                    "kind": "error",
                },
                {
                    "row": 6,
                    "column": "",
                    "message": "A contact with sam@fabrikam.example already exists.",
                    "value": "",
                    "kind": "skipped",
                },
            ],
            created_by_user_id=user.id,
        )
    )
    for lead_key, tag_names in (
        ("fabrikam", ["Priority", "SaaS"]),
        ("northwind", ["Warm intro"]),
        ("contoso", ["SaaS"]),
    ):
        for tn in tag_names:
            db.add(LeadTag(workspace_id=wid, lead_id=leads[lead_key].id, tag_id=tags[tn].id))

    # --- opportunities, activities, tasks -----------------------------------------------------
    opps = {}
    for key, stage, amount, currency, prob, status, loss in (
        ("fabrikam", "proposal", "12000.00", "USD", 60, "open", None),
        ("northwind", "meeting", "6500.00", "USD", 40, "open", None),
        (
            "contoso",
            "contacted",
            "4000.00",
            "EUR",
            None,
            "open",
            None,
        ),  # no probability: not guessed
        (
            "tailspin",
            "lost",
            "2500.00",
            "USD",
            None,
            "lost",
            "Not a client type I take (fictional)",
        ),
    ):
        o = Opportunity(
            workspace_id=wid,
            lead_id=leads[key].id,
            stage_id=stages[stage].id,
            title=f"{companies[key].name} project",
            status=status,
            value_amount=Decimal(amount),
            currency=currency,
            probability=prob,
            expected_close_date=date.today() + timedelta(days=30) if status == "open" else None,
            loss_reason=loss,
            closed_at=now - timedelta(days=2) if status != "open" else None,
            owner_user_id=user.id,
            is_sample=True,
        )
        db.add(o)
        opps[key] = o
    db.flush()
    db.add(
        Activity(
            workspace_id=wid,
            lead_id=leads["fabrikam"].id,
            opportunity_id=opps["fabrikam"].id,
            actor_user_id=user.id,
            kind="note",
            summary="Discovery call notes (fictional)",
            occurred_at=now - timedelta(days=1),
        )
    )
    db.add(
        Activity(
            workspace_id=wid,
            lead_id=leads["northwind"].id,
            kind="stage_change",
            summary="Moved to Replied",
            details={"from": "contacted", "to": "replied"},
            occurred_at=now - timedelta(hours=5),
        )
    )
    task_rows: list[tuple[str, datetime | None, str, str, str | None, str | None]] = [
        (
            "Follow up with Northwind (overdue)",
            now - timedelta(days=1),
            "high",
            "open",
            "northwind",
            None,
        ),
        (
            "Send Fabrikam proposal",
            now + timedelta(hours=6),
            "high",
            "open",
            "fabrikam",
            "fabrikam",
        ),
        ("Research Tailspin", now + timedelta(days=3), "low", "open", None, None),
        ("Review pricing notes (no due date)", None, "normal", "open", None, None),
        (
            "Send intro email to Northwind",
            now - timedelta(days=3),
            "normal",
            "done",
            "northwind",
            None,
        ),
    ]
    for title, due, prio, task_status, task_lead, task_opp in task_rows:
        db.add(
            Task(
                workspace_id=wid,
                title=title,
                due_at=due,
                due_timezone="Europe/Berlin" if due else None,
                priority=prio,
                status=task_status,
                completed_at=now - timedelta(days=2) if task_status == "done" else None,
                assignee_user_id=user.id,
                lead_id=leads[task_lead].id if task_lead else None,
                opportunity_id=opps[task_opp].id if task_opp else None,
                is_sample=True,
            )
        )

    # --- email (demo mailbox), suppression, integration --------------------------------------
    acct = EmailAccount(
        workspace_id=wid,
        provider="demo",
        provider_account_id="demo-mailbox",
        email_address="alex@alex-rivera.example",
        display_name="Alex Rivera (demo)",
        status="demo",
        is_demo=True,
    )
    db.add(acct)
    db.add(
        IntegrationConnection(
            workspace_id=wid,
            connector="demo_email",
            external_account_id="demo-mailbox",
            display_name="Demo mailbox (no real account)",
            status="demo",
            capabilities=["read", "draft"],
            config={"note": "sample data only"},
        )
    )
    db.flush()
    conv = Conversation(
        workspace_id=wid,
        email_account_id=acct.id,
        provider_thread_id="demo-thread-1",
        subject="Re: Website rebuild (fictional)",
        lead_id=leads["northwind"].id,
        contact_id=contacts["northwind"].id,
        last_message_at=now - timedelta(hours=5),
        classification="interested",
        classification_confidence=0.86,
        classification_explanation="Demo classification (mock, not a real model).",
        is_sample=True,
    )
    db.add(conv)
    db.flush()
    db.add(
        Message(
            workspace_id=wid,
            email_account_id=acct.id,
            conversation_id=conv.id,
            provider_message_id="demo-msg-1",
            direction="outbound",
            delivery_state="demo",
            from_address=acct.email_address,
            to_addresses=[contacts["northwind"].email or ""],
            subject="Website rebuild",
            snippet="Hi Jordan, fictional outreach message.",
            sent_at=now - timedelta(days=2),
            is_sample=True,
        )
    )
    db.add(
        Message(
            workspace_id=wid,
            email_account_id=acct.id,
            conversation_id=conv.id,
            provider_message_id="demo-msg-2",
            direction="inbound",
            delivery_state="demo",
            from_address=contacts["northwind"].email or "",
            to_addresses=[acct.email_address],
            subject="Re: Website rebuild",
            snippet="Sounds interesting, can we talk next week? (fictional)",
            sent_at=now - timedelta(hours=5),
            is_sample=True,
        )
    )
    draft = Draft(
        workspace_id=wid,
        lead_id=leads["northwind"].id,
        conversation_id=conv.id,
        email_account_id=acct.id,
        to_address=contacts["northwind"].email,
        subject="Re: Website rebuild",
        body_text="Hi Jordan, happy to talk next week. (fictional demo draft)",
        status="pending_approval",
        author="ai",
        content_hash="demo-hash-1",
        is_sample=True,
    )
    db.add(draft)
    db.add(
        SuppressionEntry(
            workspace_id=wid,
            email_normalized="unsubscribed@nowhere.example",
            reason="unsubscribe",
            source="seed",
            note="Fictional opted-out address",
        )
    )
    db.flush()

    # --- workflow (starter template, draft + test mode) and one test run ----------------------
    wf = Workflow(
        workspace_id=wid,
        name="New lead -> assess -> draft -> approval (demo)",
        description="Starter template. Draft/test mode; never sends on its own.",
        status="draft",
        mode="test",
        created_by_user_id=user.id,
    )
    db.add(wf)
    db.flush()
    nodes = [
        {"key": "trigger", "type": "trigger", "config": {"event": "lead.created"}},
        {"key": "assess", "type": "ai_assess_fit", "config": {}},
        {"key": "draft", "type": "ai_draft", "config": {}},
        {"key": "approve", "type": "approval_gate", "config": {"expires_hours": 48}},
        {"key": "send", "type": "send_email", "config": {}},
    ]
    edges = [
        {"key": "e1", "source": "trigger", "target": "assess"},
        {"key": "e2", "source": "assess", "target": "draft"},
        {"key": "e3", "source": "draft", "target": "approve"},
        {"key": "e4", "source": "approve", "target": "send"},
    ]
    ver = WorkflowVersion(
        workspace_id=wid,
        workflow_id=wf.id,
        version=1,
        checksum=definition_checksum(nodes, edges),
        created_by_user_id=user.id,
        note="Seeded starter template",
    )
    db.add(ver)
    db.flush()
    for i, n in enumerate(nodes):
        db.add(
            WorkflowNode(
                workspace_id=wid,
                version_id=ver.id,
                node_key=n["key"],
                type=n["type"],
                config=n["config"],
                position_x=float(i * 220),
                position_y=0.0,
            )
        )
    db.flush()
    for e in edges:
        db.add(
            WorkflowEdge(
                workspace_id=wid,
                version_id=ver.id,
                edge_key=e["key"],
                source_key=e["source"],
                target_key=e["target"],
            )
        )
    run = WorkflowRun(
        workspace_id=wid,
        workflow_id=wf.id,
        version_id=ver.id,
        status="waiting_approval",
        mode="test",
        trigger_type="manual",
        trigger_payload={"lead": "demo"},
        idempotency_key="seed-run-1",
        correlation_id=uuid.uuid4().hex,
        started_at=now,
    )
    db.add(run)
    db.flush()
    step = WorkflowStepRun(
        workspace_id=wid,
        run_id=run.id,
        node_key="approve",
        attempt=1,
        status="waiting",
        started_at=now,
        output_summary={"note": "awaiting human approval"},
    )
    db.add(step)
    db.flush()
    db.add(
        ApprovalRequest(
            workspace_id=wid,
            run_id=run.id,
            step_run_id=step.id,
            draft_id=draft.id,
            kind="send_email",
            target_type="lead",
            target_id=str(leads["northwind"].id),
            payload_hash="demo-hash-1",
            proposed_payload={"to": "redacted", "subject": draft.subject},
            status="pending",
            requested_by_user_id=None,
            expires_at=now + timedelta(hours=48),
        )
    )
    db.add(
        UsageRecord(
            workspace_id=wid,
            kind="ai_request",
            provider="mock",
            model="mock-model",
            task_type="draft_outreach",
            input_tokens=420,
            output_tokens=180,
            estimated_cost_micros=0,
            latency_ms=35,
            success=True,
            is_mock=True,
            correlation_id=run.correlation_id,
        )
    )
    db.add(
        Notification(
            workspace_id=wid,
            user_id=user.id,
            kind="approval_pending",
            title="A draft is waiting for your approval (demo)",
            link="/automations",
            dedupe_key="seed-approval-1",
        )
    )
    db.flush()
    return True, wid


def seed_workspace_id(db: DbSession) -> uuid.UUID | None:
    user = db.scalar(select(User).where(User.email_normalized == DEMO_EMAIL))
    if user is None:
        return None
    return db.scalar(select(Membership.workspace_id).where(Membership.user_id == user.id))
