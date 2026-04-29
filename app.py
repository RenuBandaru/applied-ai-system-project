import streamlit as st
from datetime import datetime
from pawpal_system import Owner, Pet, Task, Scheduler  # Phase 2 classes

try:
    from ai_parser import parse_task_from_text
    _AI_AVAILABLE = True
except ImportError as _e:
    _AI_AVAILABLE = False
    _AI_IMPORT_ERROR = str(_e)

try:
    from ai_planner import run_planner_agent
    _PLANNER_AVAILABLE = True
except ImportError as _pe:
    _PLANNER_AVAILABLE = False
    _PLANNER_IMPORT_ERROR = str(_pe)

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")

# ── Session-state bootstrap ──────────────────────────────────────────────────
# Streamlit reruns the entire script on every interaction.
# st.session_state persists objects across reruns so we don't lose data.
# We initialize each key only once (on the very first load).
if "scheduler" not in st.session_state:
    st.session_state.scheduler = Scheduler()
if "owner" not in st.session_state:
    st.session_state.owner = None
if "pet" not in st.session_state:
    st.session_state.pet = None
# NL tab: store parse result and task outcome so they survive reruns
if "nl_parse_result" not in st.session_state:
    st.session_state.nl_parse_result = None
if "nl_parse_error" not in st.session_state:
    st.session_state.nl_parse_error = None
if "nl_task_status" not in st.session_state:
    st.session_state.nl_task_status = None
# Planner: store proposed task list and error so they survive reruns
if "planner_proposal" not in st.session_state:
    st.session_state.planner_proposal = None  # list[Task] or None
if "planner_error" not in st.session_state:
    st.session_state.planner_error = None     # error string or None

# ── Section 1: Owner & Pet registration ─────────────────────────────────────
# The user provides a name, pet name, and species.
# Clicking "Register" creates real Owner and Pet objects from pawpal_system.py.
st.subheader("Owner & Pet")
col_o, col_p = st.columns(2)
with col_o:
    owner_name = st.text_input("Owner name", value="Jordan")
with col_p:
    pet_name = st.text_input("Pet name", value="Mochi")

col_s, col_a = st.columns(2)
with col_s:
    species = st.selectbox("Species", ["dog", "cat", "other"])
with col_a:
    pet_age = st.number_input("Pet age (years)", min_value=0, max_value=30, value=1)

if st.button("Register owner & pet"):
    scheduler = st.session_state.scheduler
    owner_id  = owner_name.lower().replace(" ", "_")

    # Reuse the existing owner if the same owner_id registers again so pets accumulate.
    # Creating a new Owner each time overwrites the previous one and loses all prior pets.
    if (st.session_state.owner is not None
            and st.session_state.owner.owner_id == owner_id):
        owner = st.session_state.owner
    else:
        owner = Owner(
            owner_id=owner_id,
            name=owner_name,
            email="",
            phone="",
            scheduler=scheduler,
        )
        scheduler.owners[owner_id] = owner
        st.session_state.owner = owner

    pet = Pet(
        name=pet_name,
        species=species,
        breed="unknown",
        age=pet_age,
        weight=0.0,
        owner_id=owner_id,
    )
    owner.add_pet(pet)
    st.session_state.pet = pet

# Persistent registration status — shown on every rerun, not just after clicking Register.
if st.session_state.owner is not None:
    o    = st.session_state.owner
    pets = o.get_pets()
    st.info(
        f"**Registered:** {o.name} · "
        + ", ".join(f"{p.name} ({p.species}, {p.age} yr{'s' if p.age != 1 else ''})" for p in pets)
    )
    # Pet selector — only shown when more than one pet is registered.
    if len(pets) > 1:
        selected_name = st.selectbox(
            "Active pet (used for task entry below)",
            [p.name for p in pets],
            key="active_pet_selector",
        )
        st.session_state.pet = next(p for p in pets if p.name == selected_name)
else:
    st.caption("No owner registered yet. Fill in the fields above and click Register.")

st.divider()

# ── Section 2: Add a Task ─────────────────────────────────────────────────────
# Two paths to create a task:
#   • Manual Entry  — fill out the fields yourself (original behaviour)
#   • AI Entry      — type a sentence; Claude extracts the fields for you
#
# Both paths produce the same Task object and call the same Scheduler.add_task()
# so conflict detection, priority sorting, and recurrence all behave identically.
st.subheader("Tasks")

tab_manual, tab_nl = st.tabs(["📋 Manual Entry", "✨ AI – Describe in Plain English"])

# ── Tab 1: Manual Entry (original form, unchanged) ───────────────────────────
with tab_manual:
    st.caption("Fill in the fields to add a task directly.")

    col1, col2, col3 = st.columns(3)
    with col1:
        task_title = st.text_input("Task title", value="Morning walk")
    with col2:
        duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
    with col3:
        task_type = st.selectbox("Type", ["feeding", "grooming", "medication", "vet", "exercise"])

    col4, col5 = st.columns(2)
    with col4:
        due_date = st.date_input("Due date", value=datetime.today())
    with col5:
        due_time = st.time_input("Due time", value=datetime.now().replace(second=0, microsecond=0).time())

    recurrence = st.selectbox("Recurrence", ["none", "daily", "weekly", "monthly"])

    if st.button("Add task", key="manual_add"):
        if st.session_state.owner is None or st.session_state.pet is None:
            st.warning("Please register an owner and pet first.")
        else:
            owner: Owner = st.session_state.owner
            pet: Pet = st.session_state.pet
            scheduler: Scheduler = st.session_state.scheduler

            task = Task(
                task_id=f"t{len(scheduler.tasks) + 1}",
                type=task_type,
                description=f"{task_title} ({duration} min)",
                pet_id=pet.name,
                owner_id=owner.owner_id,
                due_date=datetime.combine(due_date, due_time),
                recurrence=recurrence if recurrence != "none" else None,
            )

            conflict = scheduler.add_task(task, pet)
            if conflict:
                st.warning(f"Task added with a scheduling conflict:\n\n{conflict}")
            else:
                st.success(f"Task added: {task.description}")

# ── Tab 2: AI – Natural Language Entry ───────────────────────────────────────
# Results are stored in st.session_state so they survive the rerun that happens
# after the spinner disappears — this is why a single click is enough.
with tab_nl:
    if not _AI_AVAILABLE:
        st.error(
            f"AI features unavailable ({_AI_IMPORT_ERROR}). "
            "Run: pip install -r requirements.txt"
        )
    else:
        st.caption(
            "Describe what your pet needs in plain English. "
            "The AI extracts the type, date, and recurrence for you."
        )
        nl_text = st.text_area(
            "Task description",
            placeholder=(
                'e.g. "Flea medication every two weeks starting tomorrow at 9am"\n'
                'e.g. "Daily feeding at 7am"\n'
                'e.g. "Vet checkup next Monday afternoon"'
            ),
            height=100,
            key="nl_text_input",
        )

        if st.button("Add task from description", key="nl_add"):
            # Clear any result from a previous click before running the new one.
            st.session_state.nl_parse_result = None
            st.session_state.nl_parse_error = None
            st.session_state.nl_task_status = None

            if st.session_state.owner is None or st.session_state.pet is None:
                st.session_state.nl_parse_error = "Please register an owner and pet first."
            elif not nl_text.strip():
                st.session_state.nl_parse_error = "Please enter a task description before clicking Add."
            else:
                owner: Owner = st.session_state.owner
                pet: Pet = st.session_state.pet
                scheduler: Scheduler = st.session_state.scheduler

                with st.spinner("Parsing your description with AI…"):
                    parsed, error = parse_task_from_text(
                        user_text=nl_text,
                        pet_name=pet.name,
                        owner_id=owner.owner_id,
                    )

                if error:
                    st.session_state.nl_parse_error = error
                else:
                    task = Task(
                        task_id=f"t{len(scheduler.tasks) + 1}",
                        type=parsed["type"],
                        description=parsed["description"],
                        pet_id=pet.name,
                        owner_id=owner.owner_id,
                        due_date=parsed["due_date"],
                        recurrence=parsed["recurrence"],
                    )
                    conflict = scheduler.add_task(task, pet)
                    st.session_state.nl_parse_result = parsed
                    st.session_state.nl_task_status = (
                        ("warning", conflict) if conflict else ("success", task.description)
                    )

        # ── Results rendered outside the button block ─────────────────────────
        # These run on every rerun so the output stays visible after the spinner
        # completes and Streamlit re-renders the page.
        if st.session_state.nl_parse_error:
            st.error(f"Could not parse task: {st.session_state.nl_parse_error}")

        if st.session_state.nl_parse_result:
            p = st.session_state.nl_parse_result
            with st.expander("What the AI extracted", expanded=True):
                st.json({
                    "type": p["type"],
                    "description": p["description"],
                    "due_date": p["due_date"].strftime("%Y-%m-%d %H:%M"),
                    "recurrence": p["recurrence"] or "none",
                })
            if st.session_state.nl_task_status:
                kind, msg = st.session_state.nl_task_status
                if kind == "warning":
                    st.warning(f"Task added with a scheduling conflict:\n\n{msg}")
                else:
                    st.success(f"Task added: {msg}")

# ── Task list: split into Pending / Completed tabs ───────────────────────────
# Uses Scheduler.get_tasks_by_status() so both tabs are sorted by due_date
# rather than raw insertion order. Completed tasks are preserved as history.
scheduler_ref: Scheduler = st.session_state.scheduler
pending_tasks   = scheduler_ref.get_tasks_by_status("pending")
completed_tasks = scheduler_ref.get_tasks_by_status("completed")

# Metrics give a quick at-a-glance count before the table loads
m1, m2, m3 = st.columns(3)
m1.metric("Pending",   len(pending_tasks))
m2.metric("Completed", len(completed_tasks))
m3.metric("Total",     len(scheduler_ref.tasks))

# Priority badge shown next to each task type so urgency is visible at a glance
PRIORITY_LABEL = {
    "medication": "🔴 medication",
    "vet":        "🟠 vet",
    "feeding":    "🟡 feeding",
    "exercise":   "🟢 exercise",
    "grooming":   "🔵 grooming",
}

tab_pending, tab_completed = st.tabs(["Pending", "Completed"])

with tab_pending:
    if pending_tasks:
        st.dataframe(
            [
                {
                    "Priority": PRIORITY_LABEL.get(t.type, f"⚪ {t.type}"),
                    "Description": t.description,
                    "Pet": t.pet_id,
                    "Due": t.due_date.strftime("%b %d  %H:%M"),
                    "Recurrence": t.recurrence or "—",
                    "ID": t.task_id,
                }
                for t in pending_tasks   # already sorted by due_date from get_tasks_by_status()
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No pending tasks yet. Add one above.")

with tab_completed:
    if completed_tasks:
        st.dataframe(
            [
                {
                    "Type": t.type,
                    "Description": t.description,
                    "Pet": t.pet_id,
                    "Was due": t.due_date.strftime("%b %d  %H:%M"),
                    "Recurrence": t.recurrence or "—",
                    "ID": t.task_id,
                }
                for t in completed_tasks
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No completed tasks yet.")

st.divider()

# ── Section 3: Build Schedule ─────────────────────────────────────────────────
# Calls Scheduler methods to surface upcoming and overdue tasks.
# No new data is created here — this is purely a read/query operation.
st.subheader("Build Schedule")

# The slider controls how far ahead to look when calling get_upcoming_tasks()
days_ahead = st.slider("Show tasks due within (days)", min_value=1, max_value=30, value=7)

if st.button("Generate schedule"):
    scheduler: Scheduler = st.session_state.scheduler

    # get_upcoming_tasks() — sorted by (due_date, medical priority) via Scheduler
    upcoming = scheduler.get_upcoming_tasks(days_ahead)
    # check_overdue_tasks() — oldest overdue first, delegates to Task.is_overdue()
    overdue  = scheduler.check_overdue_tasks()

    if not upcoming and not overdue:
        st.info("No upcoming or overdue tasks in the selected window.")
    else:
        # ── Overdue tasks ── shown first so critical items are never buried
        if overdue:
            st.markdown("#### Overdue Tasks")
            for t in overdue:
                st.error(
                    f"**OVERDUE** — {t.description}  |  "
                    f"{PRIORITY_LABEL.get(t.type, t.type)}  |  "
                    f"was due {t.due_date.strftime('%b %d  %H:%M')}"
                )

        # ── Upcoming tasks ── rendered as a styled dataframe so columns are scannable
        if upcoming:
            st.markdown("#### Upcoming Tasks")

            # Rows are already priority-sorted by Scheduler.get_upcoming_tasks()
            rows = []
            for t in upcoming:
                rows.append({
                    "Priority": PRIORITY_LABEL.get(t.type, f"⚪ {t.type}"),
                    "Description": t.description,
                    "Pet": t.pet_id,
                    "Due": t.due_date.strftime("%b %d  %H:%M"),
                    "Recurrence": f"↻ {t.recurrence}" if t.recurrence else "—",
                })

            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.success(
                f"{len(upcoming)} task{'s' if len(upcoming) != 1 else ''} scheduled "
                f"over the next {days_ahead} day{'s' if days_ahead != 1 else ''}."
            )

st.divider()

# ── Section 4: AI Care Planner ────────────────────────────────────────────────
# The agent calls four tools that query real Pet / Scheduler data before
# proposing tasks. Tasks only enter the Scheduler after the user clicks Confirm.
# Results are stored in session_state so they survive Streamlit reruns.
st.subheader("AI Care Planner")

if not _PLANNER_AVAILABLE:
    st.error(
        f"Planner unavailable ({_PLANNER_IMPORT_ERROR}). "
        "Run: pip install -r requirements.txt"
    )
else:
    st.caption(
        "Describe a care goal in one sentence. The AI reads your pet's profile and "
        "current schedule, checks for conflicts, and proposes a full task plan."
    )

    goal_text = st.text_area(
        "Care goal",
        placeholder=(
            'e.g. "Luna just had surgery — set up a 2-week recovery plan"\n'
            'e.g. "Buddy needs a complete wellness routine starting next week"\n'
            'e.g. "Set up monthly grooming and weekly exercise for Mochi"'
        ),
        height=90,
        key="planner_goal",
    )

    if st.button("Generate care plan", key="planner_generate"):
        st.session_state.planner_proposal = None
        st.session_state.planner_error    = None

        if st.session_state.owner is None or st.session_state.pet is None:
            st.session_state.planner_error = "Please register an owner and pet first."
        elif not goal_text.strip():
            st.session_state.planner_error = "Please enter a care goal before generating a plan."
        else:
            owner: Owner       = st.session_state.owner
            pet: Pet           = st.session_state.pet
            scheduler: Scheduler = st.session_state.scheduler

            with st.spinner("AI agent is reading your pet's profile, checking the schedule, and building a plan…"):
                tasks, error = run_planner_agent(goal_text, pet, owner, scheduler)

            if error:
                st.session_state.planner_error = error
            else:
                st.session_state.planner_proposal = tasks

    # ── Results rendered outside the button block so they survive reruns ──────
    if st.session_state.planner_error:
        st.error(st.session_state.planner_error)

    if st.session_state.planner_proposal:
        proposal = st.session_state.planner_proposal
        st.markdown(f"**{len(proposal)} task{'s' if len(proposal) != 1 else ''} proposed** — review below, then confirm to add them to your schedule.")

        st.dataframe(
            [
                {
                    "Priority":    PRIORITY_LABEL.get(t.type, f"⚪ {t.type}"),
                    "Description": t.description,
                    "Due":         t.due_date.strftime("%b %d  %H:%M"),
                    "Recurrence":  f"↻ {t.recurrence}" if t.recurrence else "—",
                }
                for t in proposal
            ],
            use_container_width=True,
            hide_index=True,
        )

        if st.button("Confirm and add all tasks", key="planner_confirm"):
            owner: Owner         = st.session_state.owner
            pet: Pet             = st.session_state.pet
            scheduler: Scheduler = st.session_state.scheduler
            conflicts = []

            for task in proposal:
                # Assign a proper sequential task_id before adding to the Scheduler
                task.task_id = f"t{len(scheduler.tasks) + 1}"
                conflict = scheduler.add_task(task, pet)
                if conflict:
                    conflicts.append(conflict)

            st.session_state.planner_proposal = None  # clear the proposal

            if conflicts:
                st.warning(
                    f"{len(proposal)} task{'s' if len(proposal) != 1 else ''} added with "
                    f"{len(conflicts)} conflict{'s' if len(conflicts) != 1 else ''}:\n\n"
                    + "\n".join(conflicts)
                )
            else:
                st.success(
                    f"{len(proposal)} task{'s' if len(proposal) != 1 else ''} added to your schedule."
                )
