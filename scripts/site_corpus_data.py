"""Authored content taxonomy for the HR, Manufacturing, and Sales & Marketing knowledge hubs.

Replaces the old generic "Quality"/"Engineering" folders and numbered placeholder files
(hr_docx_01.docx, hr_meeting_04.mp4, ...) with a department structure and document/meeting
topics that mirror how a real company organizes a SharePoint knowledge hub, and with real,
distinct written content per document instead of copies of a single template.

Each site has:
  - ``departments``: ordered list of {folder, documents: [...]}. Every document topic carries
    real title, narrative paragraphs, and bullet points; a ``doc_type`` of "policy"/"procedure"/
    "report" renders to DOCX or PDF, "tracker" renders to XLSX, "deck" renders to PPTX.
  - ``meetings``: a "Meeting Recordings and Transcripts" folder of distinct meeting topics, each
    with its own agenda and per-speaker talking points (no two meetings share a transcript).
  - ``participants``: the recurring cast of people who appear across that site's meetings.
"""

from __future__ import annotations

PARTICIPANTS: dict[str, list[tuple[str, str]]] = {
    "hr": [
        ("Maria Chen", "VP of People"),
        ("Devon Russell", "HR Business Partner"),
        ("Priya Natarajan", "Talent Acquisition Lead"),
        ("Sam Whitfield", "Total Rewards Manager"),
        ("Alicia Gomez", "Learning & Development Manager"),
        ("Ben Okafor", "Employee Relations Specialist"),
    ],
    "manufacturing": [
        ("Theo Marsh", "Plant Manager"),
        ("Linda Park", "Quality Assurance Manager"),
        ("Carlos Ibarra", "Process Engineering Lead"),
        ("Grace Liu", "Production Supervisor"),
        ("Omar Haddad", "Supply Chain Manager"),
        ("Dana Fitzgerald", "EHS Coordinator"),
    ],
    "sales": [
        ("Rachel Kim", "VP of Sales"),
        ("Marcus Lee", "Sales Enablement Manager"),
        ("Sofia Alvarez", "Field Marketing Manager"),
        ("Tom Bergstrom", "Customer Success Director"),
        ("Nina Patel", "Competitive Intelligence Analyst"),
        ("Jake Thompson", "Regional Sales Manager"),
    ],
}

SITE_LABELS = {
    "hr": "HR Knowledge Hub",
    "manufacturing": "Manufacturing Knowledge Hub",
    "sales": "Sales & Marketing Knowledge Hub",
}


def _doc(title, doc_type, summary, points, owner, table=None, metrics=None):
    return {
        "title": title,
        "doc_type": doc_type,
        "summary": summary,
        "points": points,
        "owner": owner,
        "table": table or [],
        "metrics": metrics or {},
    }


def _meeting(title, folder, agenda):
    """``agenda`` is a list of (speaker_index, line) pairs; speaker_index indexes PARTICIPANTS."""
    return {"title": title, "folder": folder, "agenda": agenda}


# ---------------------------------------------------------------------------
# HR
# ---------------------------------------------------------------------------

HR_DEPARTMENTS = [
    {
        "folder": "HR Policies",
        "documents": [
            _doc(
                "Employee Handbook - Code of Conduct",
                "policy",
                "Defines the standards of professional conduct expected of every employee, "
                "including workplace respect, conflicts of interest, and use of company assets.",
                [
                    "Zero tolerance for harassment, discrimination, or retaliation of any kind.",
                    "Employees must disclose outside employment or financial interests that could "
                    "create a conflict with company business.",
                    "Company equipment, accounts, and data may only be used for authorized purposes.",
                    "Violations are investigated by Employee Relations and may result in corrective "
                    "action up to and including termination.",
                ],
                "Maria Chen",
            ),
            _doc(
                "Flexible Work and Remote Work Policy",
                "policy",
                "Describes eligibility, expectations, and equipment support for employees working "
                "remotely or on a hybrid schedule.",
                [
                    "Hybrid roles require a minimum of two in-office days coordinated with the team lead.",
                    "Remote employees receive a one-time $750 home office stipend on hire.",
                    "Core collaboration hours are 10:00 AM - 3:00 PM in the employee's local time zone.",
                    "Managers approve remote work arrangements annually during the performance cycle.",
                ],
                "Devon Russell",
            ),
            _doc(
                "Paid Time Off and Leave of Absence Policy",
                "policy",
                "Summarizes accrual rates, blackout periods, and the process for requesting extended "
                "leave, including parental and medical leave.",
                [
                    "Full-time employees accrue 1.25 PTO days per month, capped at 30 days banked.",
                    "Parental leave provides 12 weeks paid for the primary caregiver and 6 weeks for the secondary caregiver.",
                    "Leave requests over 10 consecutive days require HR Business Partner sign-off.",
                    "Unused PTO above the cap is forfeited at calendar year end per state requirements.",
                ],
                "Devon Russell",
            ),
            _doc(
                "Workplace Safety and Incident Reporting Policy",
                "policy",
                "Sets expectations for a safe office and lab environment and the steps for reporting "
                "an injury, near-miss, or safety hazard.",
                [
                    "Any workplace injury must be reported to Facilities and HR within 24 hours.",
                    "Ergonomic assessments are available on request through the Facilities portal.",
                    "Building evacuation drills are conducted twice per year per site.",
                    "Repeat hazards identified in incident reports trigger a facilities corrective action review.",
                ],
                "Ben Okafor",
            ),
            _doc(
                "Data Privacy and Confidentiality Policy",
                "policy",
                "Explains how employee and candidate personal data is collected, stored, and shared, "
                "and the obligations employees have when handling confidential HR records.",
                [
                    "HR records are retained for 7 years after separation, then securely purged.",
                    "Access to compensation and medical data is restricted to HR Business Partners and Total Rewards.",
                    "Background check results may not be shared outside the hiring committee.",
                    "Any suspected data exposure must be reported to IT Security within one business day.",
                ],
                "Maria Chen",
            ),
            _doc(
                "Diversity, Equity, and Inclusion Policy",
                "policy",
                "Outlines the company's commitments to equitable hiring, pay equity reviews, and "
                "employee resource groups.",
                [
                    "Hiring panels must include at least one member from outside the hiring manager's team.",
                    "Pay equity analysis is run twice yearly across all job families.",
                    "Four employee resource groups are funded with an annual budget and executive sponsor.",
                    "DEI progress is reported to the leadership team each quarter.",
                ],
                "Maria Chen",
            ),
        ],
    },
    {
        "folder": "Recruiting and Onboarding",
        "documents": [
            _doc(
                "Manager's Guide to Structured Interviewing",
                "procedure",
                "Walks hiring managers through building a scorecard, running a structured interview "
                "loop, and submitting calibrated feedback.",
                [
                    "Every loop uses a shared scorecard with 4-5 competencies agreed before scheduling.",
                    "Interviewers submit written feedback within 24 hours of the interview.",
                    "Debriefs are led by the recruiter and require a clear hire/no-hire recommendation.",
                    "Panels avoid duplicate competency coverage by splitting the scorecard in advance.",
                ],
                "Priya Natarajan",
            ),
            _doc(
                "New Hire 30-60-90 Day Onboarding Plan",
                "procedure",
                "Gives new hires and their managers a shared plan for ramp-up milestones across the "
                "first three months.",
                [
                    "Day 30: complete required compliance training and meet core cross-team partners.",
                    "Day 60: own a first individual deliverable with manager checkpoints weekly.",
                    "Day 90: present ramp-up summary and set goals for the next quarter.",
                    "Buddy program pairs every new hire with a peer outside their direct team.",
                ],
                "Priya Natarajan",
            ),
            _doc(
                "Background Check and Offer Approval Matrix",
                "tracker",
                "Tracks background check vendor SLAs and the approval chain required before an offer "
                "can be extended at each job level.",
                [
                    "Standard background checks complete within 3 business days through the vendor portal.",
                    "Director-and-above offers require VP of People sign-off before extension.",
                    "Education verification failures are escalated to the hiring manager and HRBP.",
                    "Offer letters are void if background checks are not cleared within 10 business days.",
                ],
                "Priya Natarajan",
                table=[
                    ("Job Level", "Approval Required", "Target SLA"),
                    ("Individual Contributor", "Hiring Manager", "3 business days"),
                    ("Manager", "Hiring Manager + HRBP", "3 business days"),
                    ("Director", "VP of People", "5 business days"),
                    ("Executive", "CEO + VP of People", "7 business days"),
                ],
            ),
            _doc(
                "Employee Referral Program Guide",
                "procedure",
                "Explains referral bonus tiers, eligible roles, and the payout schedule tied to "
                "new hire retention milestones.",
                [
                    "Standard roles pay a $2,000 referral bonus; hard-to-fill engineering roles pay $4,000.",
                    "Half of the bonus is paid at hire and half after the referred employee's 90-day mark.",
                    "Referrals are ineligible for roles the referrer's own manager is hiring for.",
                    "Program performance is reviewed quarterly against overall sourcing mix.",
                ],
                "Priya Natarajan",
            ),
            _doc(
                "Recruiting Pipeline and Requisition Tracker",
                "tracker",
                "Weekly snapshot of open requisitions, pipeline stage counts, and time-to-fill against "
                "target by department.",
                [
                    "Requisitions open longer than 60 days are flagged for a sourcing strategy review.",
                    "Time-to-fill target is 35 days for individual contributor roles.",
                    "Pipeline health is measured by applicants-to-onsite conversion rate.",
                    "Stale requisitions with no activity in 14 days are escalated to the recruiting lead.",
                ],
                "Priya Natarajan",
                table=[
                    ("Department", "Open Reqs", "Avg Days Open", "Pipeline Stage"),
                    ("Engineering", "6", "41", "Onsite"),
                    ("Sales", "4", "28", "Phone Screen"),
                    ("Operations", "2", "19", "Offer"),
                    ("Finance", "1", "52", "Sourcing"),
                ],
            ),
        ],
    },
    {
        "folder": "Compensation and Benefits",
        "documents": [
            _doc(
                "Annual Merit Increase Cycle Guide",
                "procedure",
                "Explains the merit budget allocation, calibration process, and manager communication "
                "timeline for the annual compensation review.",
                [
                    "Merit budget is allocated by department based on performance distribution and market data.",
                    "Calibration sessions run for two weeks before increases are finalized.",
                    "Managers deliver compensation conversations in 1:1s, never over email.",
                    "Off-cycle adjustments require Total Rewards and VP approval with written justification.",
                ],
                "Sam Whitfield",
            ),
            _doc(
                "Health Plan Comparison Guide",
                "report",
                "Compares the three medical plan tiers offered during open enrollment, including "
                "premiums, deductibles, and HSA eligibility.",
                [
                    "PPO Plus has the lowest deductible but the highest monthly premium.",
                    "HDHP with HSA includes a $600 annual employer HSA contribution.",
                    "Dependent coverage add-on costs are listed per pay period, not annually.",
                    "Plan changes outside open enrollment require a qualifying life event.",
                ],
                "Sam Whitfield",
                table=[
                    ("Plan", "Monthly Premium", "Deductible", "HSA Eligible"),
                    ("PPO Plus", "$145", "$500", "No"),
                    ("PPO Standard", "$95", "$1,500", "No"),
                    ("HDHP + HSA", "$60", "$3,200", "Yes"),
                ],
            ),
            _doc(
                "401(k) Enrollment and Employer Match Guide",
                "procedure",
                "Explains automatic enrollment defaults, the employer match formula, and vesting "
                "schedule for retirement contributions.",
                [
                    "New hires are auto-enrolled at 4% contribution after 30 days unless they opt out.",
                    "Employer matches 50% of the first 6% an employee contributes.",
                    "Employer match vests over four years on a graded schedule.",
                    "Loans against the 401(k) balance are limited to 50% of vested balance.",
                ],
                "Sam Whitfield",
            ),
            _doc(
                "Annual Bonus Plan Structure",
                "report",
                "Documents how company performance, team performance, and individual performance "
                "combine to determine the annual bonus payout multiplier.",
                [
                    "Company performance multiplier is set by the executive team based on revenue and margin targets.",
                    "Individual multiplier ranges from 0.5x to 1.5x based on performance rating.",
                    "Bonus payouts are prorated for employees hired after July 1.",
                    "Sales roles are covered by a separate commission plan, not this bonus structure.",
                ],
                "Sam Whitfield",
            ),
            _doc(
                "Relocation Assistance Policy",
                "policy",
                "Covers eligibility, reimbursable expenses, and repayment terms for employees "
                "relocating for a new role.",
                [
                    "Relocation packages are tiered by distance: under 50 miles, 50-500 miles, and over 500 miles.",
                    "Covered expenses include moving company costs, temporary housing up to 30 days, and one house-hunting trip.",
                    "Relocation assistance must be repaid in full if the employee resigns within 12 months.",
                    "International relocations route through the global mobility team, not this policy.",
                ],
                "Sam Whitfield",
            ),
        ],
    },
    {
        "folder": "Employee Relations",
        "documents": [
            _doc(
                "Performance Improvement Plan Template and Guide",
                "procedure",
                "Provides the template and manager guidance for structuring a performance improvement "
                "plan, including goal-setting and check-in cadence.",
                [
                    "PIPs run for 30, 60, or 90 days depending on the severity of the performance gap.",
                    "Goals must be specific, measurable, and reviewed weekly with the employee.",
                    "HR Business Partner reviews every PIP before it is issued to the employee.",
                    "Outcomes are documented as successful completion, extension, or separation.",
                ],
                "Ben Okafor",
            ),
            _doc(
                "Workplace Investigation Checklist",
                "procedure",
                "Step-by-step checklist used by Employee Relations when investigating a workplace "
                "complaint, from intake through resolution.",
                [
                    "Intake interview is scheduled within 2 business days of a complaint being filed.",
                    "All witnesses are interviewed separately and notes are retained in the case file.",
                    "Findings are documented using a substantiated, partially substantiated, or unsubstantiated outcome.",
                    "Complainant and respondent both receive a closure communication within 5 business days of resolution.",
                ],
                "Ben Okafor",
            ),
            _doc(
                "Grievance and Appeals Procedure",
                "policy",
                "Describes how an employee can escalate an unresolved workplace concern beyond their "
                "direct manager.",
                [
                    "Step 1 escalation goes to the employee's HR Business Partner.",
                    "Step 2 escalation, if unresolved, goes to the VP of People.",
                    "Formal grievances are logged and tracked to resolution within 15 business days.",
                    "Retaliation against an employee who files a grievance is itself a policy violation.",
                ],
                "Ben Okafor",
            ),
            _doc(
                "Exit Interview Summary and Themes Report",
                "report",
                "Quarterly rollup of voluntary departure reasons and themes surfaced in exit "
                "interviews, used to inform retention initiatives.",
                [
                    "Compensation was cited in 31% of exits this quarter, down from 38% last quarter.",
                    "Career growth concerns remain the top driver among tenure-2-to-4-year employees.",
                    "Manager relationship issues account for a small but consistent share of departures.",
                    "Findings are shared with department leads during the quarterly people review.",
                ],
                "Devon Russell",
            ),
            _doc(
                "Employee Relations Case Tracker",
                "tracker",
                "Log of open and closed employee relations cases with case type, status, and days "
                "open, used to monitor caseload and resolution time.",
                [
                    "Average case resolution time target is 10 business days.",
                    "Cases open longer than 20 business days are escalated to the VP of People.",
                    "Case types include conduct, performance, accommodation, and harassment complaints.",
                    "All case notes are stored in the restricted Employee Relations case file, not this tracker.",
                ],
                "Ben Okafor",
                table=[
                    ("Case Type", "Status", "Days Open"),
                    ("Conduct", "Closed", "8"),
                    ("Accommodation", "Open", "6"),
                    ("Performance", "Closed", "14"),
                    ("Harassment Complaint", "Open", "3"),
                ],
            ),
        ],
    },
    {
        "folder": "Learning and Development",
        "documents": [
            _doc(
                "Leadership Development Curriculum",
                "deck",
                "Overview of the four-module leadership program for newly promoted managers, "
                "covering coaching, delegation, feedback, and team operating rhythms.",
                [
                    "Module 1 covers transitioning from individual contributor to people manager.",
                    "Module 2 focuses on delivering effective, timely feedback.",
                    "Module 3 covers delegation and building team operating rhythms.",
                    "Module 4 is a capstone project presented to a panel of senior leaders.",
                ],
                "Alicia Gomez",
                metrics={"Cohort size": "18", "Completion rate": "94%", "Avg satisfaction": "4.6/5"},
            ),
            _doc(
                "Compliance Training Completion Tracker",
                "tracker",
                "Tracks completion status of mandatory compliance training modules by department "
                "against the annual deadline.",
                [
                    "Code of conduct and anti-harassment training is required annually for all employees.",
                    "Managers must complete an additional manager-specific compliance module.",
                    "Departments below 90% completion are flagged two weeks before the deadline.",
                    "Completion data feeds the quarterly compliance report to the audit committee.",
                ],
                "Alicia Gomez",
                table=[
                    ("Department", "Enrolled", "Completed", "Completion %"),
                    ("Engineering", "142", "131", "92%"),
                    ("Sales", "64", "58", "91%"),
                    ("Operations", "47", "47", "100%"),
                    ("Finance", "22", "19", "86%"),
                ],
            ),
            _doc(
                "Mentorship Program Guide",
                "procedure",
                "Explains how employees enroll in the cross-functional mentorship program and how "
                "mentor-mentee pairs are matched.",
                [
                    "Enrollment opens twice a year, in January and July.",
                    "Pairs are matched on stated growth goals rather than shared function.",
                    "Each pairing commits to a six-month cycle with monthly check-ins.",
                    "Program outcomes are measured through a mid-cycle and end-of-cycle survey.",
                ],
                "Alicia Gomez",
            ),
            _doc(
                "Skills Gap Analysis and Career Pathing Framework",
                "report",
                "Summarizes the skills gap analysis conducted across engineering and operations and "
                "proposes career pathing tracks to close the gaps.",
                [
                    "Cloud infrastructure and data analysis were the two largest identified skill gaps.",
                    "Career pathing tracks are offered for both individual contributor and management tracks.",
                    "Learning stipends of $1,500 per year support external certifications aligned to the gap areas.",
                    "Progress against pathing goals is reviewed during mid-year check-ins.",
                ],
                "Alicia Gomez",
            ),
            _doc(
                "Manager Essentials Workshop Deck",
                "deck",
                "Slide deck used in the quarterly manager essentials workshop covering 1:1 cadence, "
                "goal setting, and recognition practices.",
                [
                    "Recommends a weekly 1:1 cadence with a shared, employee-owned agenda document.",
                    "Introduces the quarterly goal-setting template aligned to department OKRs.",
                    "Covers informal recognition practices and the quarterly peer recognition awards.",
                    "Closes with a manager self-assessment exercise.",
                ],
                "Alicia Gomez",
            ),
        ],
    },
]

HR_MEETINGS_FOLDER = "Meeting Recordings and Transcripts"
HR_MEETINGS = [
    _meeting(
        "Q1 Open Enrollment Planning Review",
        HR_MEETINGS_FOLDER,
        [
            (3, "Let's walk through the three medical plan tiers before we send the open enrollment announcement."),
            (0, "The PPO Plus premium increase is larger than last year, we should flag that clearly in the communication."),
            (3, "Agreed. I'll update the comparison guide with the new premium and deductible numbers this week."),
            (1, "Onboarding will need the updated guide before the next new hire cohort starts in three weeks."),
            (0, "Let's also confirm the HSA employer contribution amount didn't change this cycle."),
            (3, "Confirmed, it stays at six hundred dollars annually for anyone enrolled in the HDHP plan."),
        ],
    ),
    _meeting(
        "New Hire Onboarding Process Audit",
        HR_MEETINGS_FOLDER,
        [
            (1, "We pulled thirty-day survey results from the last two onboarding cohorts, satisfaction dropped slightly."),
            (5, "Most of the feedback points to the buddy program not consistently kicking off in the first week."),
            (1, "I'll add a reminder task for recruiting coordinators to assign buddies before day one."),
            (0, "Let's also check whether managers are completing the day-thirty check-in consistently."),
            (5, "I can pull that from the onboarding tracker and report back by Friday."),
        ],
    ),
    _meeting(
        "Annual Performance Calibration Session",
        HR_MEETINGS_FOLDER,
        [
            (0, "Before we finalize ratings, let's review the distribution across engineering and make sure it's not skewed."),
            (2, "Engineering currently has eighteen percent in the top rating tier, which is above our target band."),
            (0, "Let's have each manager walk through their top-tier nominations with specific examples."),
            (4, "I'll make sure the calibration notes get captured for the merit cycle planning next week."),
            (2, "Agreed, and we should flag any rating changes that affect promotion readiness separately."),
        ],
    ),
    _meeting(
        "Employee Relations Case Review",
        HR_MEETINGS_FOLDER,
        [
            (5, "We have two open cases past the ten business day target, both are accommodation requests."),
            (0, "What's blocking the accommodation cases specifically?"),
            (5, "We're waiting on supporting documentation from the employee's provider on one, and facilities sign-off on the other."),
            (0, "Let's set a follow-up date for each and loop in facilities directly instead of waiting."),
            (5, "I'll send the follow-up today and update the case tracker status this afternoon."),
        ],
    ),
    _meeting(
        "DEI Employee Resource Group Budget Planning",
        HR_MEETINGS_FOLDER,
        [
            (0, "Each of the four employee resource groups submitted their budget requests for next year."),
            (4, "The mentorship-focused group is requesting additional funding for an external speaker series."),
            (0, "Let's compare that against last year's attendance numbers before approving the increase."),
            (4, "I'll pull attendance data and bring a recommendation to the next budget review."),
            (0, "We also need an executive sponsor confirmed for the newest group before funding is released."),
        ],
    ),
    _meeting(
        "Compensation Benchmarking Data Review",
        HR_MEETINGS_FOLDER,
        [
            (3, "The new market data shows our engineering bands are trailing the seventy-fifth percentile in two regions."),
            (0, "Which levels are most affected, is this concentrated at senior levels or broader?"),
            (3, "It's concentrated at senior and staff engineer levels specifically."),
            (0, "Let's model the cost of a targeted band adjustment before the merit cycle guide goes out."),
            (3, "I'll have modeling ready for review by the end of the week."),
        ],
    ),
    _meeting(
        "Manager Essentials Workshop Debrief",
        HR_MEETINGS_FOLDER,
        [
            (4, "Workshop satisfaction scores came in at four point six out of five, our highest this year."),
            (0, "What feedback did we get on the goal-setting module specifically?"),
            (4, "A few managers asked for a shorter template, the current one felt long for smaller teams."),
            (0, "Let's simplify that section before the next cohort and keep the recognition section as is."),
            (4, "I'll have a revised template ready before the next session in six weeks."),
        ],
    ),
    _meeting(
        "Referral Program Performance Review",
        HR_MEETINGS_FOLDER,
        [
            (2, "Referrals made up twenty-two percent of hires this quarter, up from fifteen percent last quarter."),
            (0, "That's a strong improvement, do we know which teams are driving most of the referrals?"),
            (2, "Engineering and sales are the two biggest contributors, operations is lagging."),
            (0, "Let's put together a short reminder campaign targeted at operations before next quarter."),
            (2, "I'll draft that and share it with the operations leadership team this week."),
        ],
    ),
    _meeting(
        "Leadership Development Cohort Kickoff",
        HR_MEETINGS_FOLDER,
        [
            (4, "This cohort has eighteen newly promoted managers, slightly larger than our usual group size."),
            (0, "Let's make sure we have enough coaching capacity for the capstone project reviews."),
            (4, "I've confirmed three senior leaders are available for the panel sessions."),
            (0, "Good, let's also send a pre-work survey so we can tailor module one to this group."),
            (4, "I'll have the survey out by end of day tomorrow."),
        ],
    ),
    _meeting(
        "Remote Work Policy Exceptions Review",
        HR_MEETINGS_FOLDER,
        [
            (1, "We've had a handful of requests for fully remote arrangements outside the standard hybrid policy."),
            (0, "Let's review them individually, exceptions should stay rare and well documented."),
            (1, "Two are relocation-related and one is a caregiving accommodation request."),
            (0, "The caregiving case should route through the accommodation process, not a policy exception."),
            (1, "I'll redirect that one and bring the other two back with manager recommendations."),
        ],
    ),
    _meeting(
        "Exit Interview Themes Quarterly Readout",
        HR_MEETINGS_FOLDER,
        [
            (0, "Compensation concerns dropped as a cited exit reason this quarter, which is encouraging."),
            (5, "Career growth is now the top theme, especially among employees in year two through four."),
            (0, "Let's connect this directly to the career pathing framework rollout timeline."),
            (4, "I can align the pathing framework communication to target that tenure band specifically."),
            (0, "Let's bring a combined recommendation to the next leadership people review."),
        ],
    ),
    _meeting(
        "401(k) Plan Vendor Check-in",
        HR_MEETINGS_FOLDER,
        [
            (3, "The vendor flagged a lower than expected auto-enrollment opt-out rate, which is good news."),
            (0, "Do we know if that's related to the recent employee communication campaign?"),
            (3, "Likely yes, enrollment emails went out right before the auto-enrollment window closed."),
            (0, "Let's keep that cadence for the next plan year and measure the impact again."),
            (3, "I'll document that in the enrollment guide update for next year."),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Manufacturing
# ---------------------------------------------------------------------------

MFG_DEPARTMENTS = [
    {
        "folder": "Quality Assurance",
        "documents": [
            _doc(
                "Incoming Material Inspection Procedure",
                "procedure",
                "Defines the sampling plan, acceptance criteria, and disposition process for raw "
                "materials received from approved suppliers.",
                [
                    "Sampling follows an AQL 1.0 plan based on lot size per ANSI/ASQ Z1.4.",
                    "Dimensional checks use calibrated gauges logged against the calibration schedule.",
                    "Nonconforming lots are quarantined and tagged pending Material Review Board decision.",
                    "Supplier is notified within 24 hours of any lot rejection with supporting measurement data.",
                ],
                "Linda Park",
            ),
            _doc(
                "Statistical Process Control Plan - Line 3",
                "procedure",
                "Specifies the control charts, sampling frequency, and out-of-control response actions "
                "for the critical dimensions monitored on Line 3.",
                [
                    "X-bar and R charts are sampled every 30 minutes on the critical bore diameter.",
                    "Operators stop the line and notify the shift lead on any out-of-control signal.",
                    "Control limits are recalculated quarterly using the most recent 25 subgroups.",
                    "Capability studies (Cpk) are rerun after any tooling change.",
                ],
                "Linda Park",
            ),
            _doc(
                "Corrective and Preventive Action (CAPA) Log",
                "tracker",
                "Tracks open CAPAs from root cause through verification of effectiveness, with owner "
                "and due date.",
                [
                    "Root cause analysis uses the 5-Why or fishbone method depending on complexity.",
                    "Containment actions must be implemented within 48 hours of CAPA opening.",
                    "Effectiveness checks are scheduled 30-60 days after corrective action implementation.",
                    "CAPAs older than 90 days without closure are escalated to the plant quality review.",
                ],
                "Linda Park",
                table=[
                    ("CAPA ID", "Issue", "Owner", "Status"),
                    ("CAPA-114", "Seal leak on Line 2", "Carlos Ibarra", "Verification"),
                    ("CAPA-118", "Label print smearing", "Linda Park", "Open"),
                    ("CAPA-121", "Torque spec drift Station 7", "Grace Liu", "Closed"),
                ],
            ),
            _doc(
                "Customer Complaint 8D Report - Bracket Assembly",
                "report",
                "Eight-discipline problem-solving report addressing a customer field complaint on a "
                "bracket assembly fatigue failure.",
                [
                    "D3 containment: all finished goods inventory of the affected lot was quarantined.",
                    "D4 root cause: weld penetration depth fell below spec on a subset of fixtures.",
                    "D5 corrective action: fixture rework and weld parameter revalidation completed.",
                    "D8 closure confirmed after 60 days of clean field performance data.",
                ],
                "Linda Park",
            ),
            _doc(
                "ISO 9001 Internal Audit Checklist",
                "procedure",
                "Checklist used by internal auditors to assess conformance to ISO 9001 clauses during "
                "the semiannual internal audit cycle.",
                [
                    "Audit covers document control, training records, and nonconformance management.",
                    "Each finding is classified as major, minor, or observation.",
                    "Auditees have 15 business days to submit a corrective action plan for major findings.",
                    "Audit results feed the management review meeting agenda.",
                ],
                "Linda Park",
            ),
            _doc(
                "Gauge and Equipment Calibration Schedule",
                "tracker",
                "Master schedule of calibration due dates for measurement equipment used across the "
                "quality lab and production floor.",
                [
                    "Calibration intervals are set by equipment type and criticality to product quality.",
                    "Equipment past due for calibration is removed from service and tagged.",
                    "External calibration vendors are audited annually against ISO 17025 accreditation.",
                    "Calibration records are retained for the life of the equipment plus three years.",
                ],
                "Linda Park",
                table=[
                    ("Equipment", "Location", "Last Calibrated", "Next Due"),
                    ("Caliper Set A", "Line 1", "2026-04-02", "2026-10-02"),
                    ("CMM Station", "Quality Lab", "2026-06-15", "2026-12-15"),
                    ("Torque Wrench 7", "Line 3 Station 7", "2026-07-20", "2027-01-20"),
                ],
            ),
        ],
    },
    {
        "folder": "Process Engineering",
        "documents": [
            _doc(
                "Process FMEA - Bracket Welding Cell",
                "report",
                "Failure mode and effects analysis for the automated welding cell, ranking failure "
                "modes by risk priority number for mitigation planning.",
                [
                    "Highest RPN failure mode is inconsistent weld penetration from electrode wear.",
                    "Mitigation adds an automated electrode wear check every 500 cycles.",
                    "Detection controls were upgraded from manual visual check to inline vision inspection.",
                    "FMEA is reviewed and updated after any process or equipment change.",
                ],
                "Carlos Ibarra",
            ),
            _doc(
                "Work Instruction Update - Station 7 Torque Sequence",
                "procedure",
                "Updated step-by-step work instruction for the torque sequence at Station 7 following "
                "a fixture redesign.",
                [
                    "Torque sequence changed from a cross pattern to a sequential pattern to reduce warping.",
                    "Target torque is 45 Nm plus or minus 2 Nm, verified by the inline torque audit.",
                    "Operators complete a one-time retraining session before working the updated station.",
                    "Work instruction revision is posted at the station and logged in the document control system.",
                ],
                "Carlos Ibarra",
            ),
            _doc(
                "Line Balancing Study - Assembly Line 2",
                "report",
                "Time study and line balancing analysis identifying the bottleneck station and "
                "proposed cycle time redistribution.",
                [
                    "Station 4 cycle time exceeded takt time by 8 seconds, creating a recurring bottleneck.",
                    "Redistributing one sub-assembly step to Station 3 reduced the bottleneck to within 2 seconds of takt.",
                    "Projected throughput improvement is approximately 6% without added headcount.",
                    "Recommendation is scheduled for pilot validation next production cycle.",
                ],
                "Carlos Ibarra",
            ),
            _doc(
                "Tooling Validation Report - New Injection Mold",
                "report",
                "Validation results for the newly commissioned injection mold tool, covering first "
                "article inspection and short-run capability.",
                [
                    "First article inspection passed all 14 critical dimensions within tolerance.",
                    "Short-run capability study produced a Cpk of 1.48 on the primary wall thickness dimension.",
                    "Mold flow simulation matched actual fill pattern within acceptable variance.",
                    "Tool is approved for production release pending preventive maintenance plan sign-off.",
                ],
                "Carlos Ibarra",
            ),
            _doc(
                "Yield Improvement Project Charter - Line 3",
                "deck",
                "Project charter kicking off a yield improvement initiative targeting the top three "
                "defect categories on Line 3.",
                [
                    "Baseline first-pass yield is 91.4%, target is 95% within two quarters.",
                    "Top defect categories are seal leaks, label misalignment, and torque out-of-spec.",
                    "Cross-functional team includes quality, process engineering, and production supervisors.",
                    "Weekly tollgate reviews track progress against the yield improvement roadmap.",
                ],
                "Carlos Ibarra",
                metrics={"Baseline yield": "91.4%", "Target yield": "95.0%", "Timeline": "2 quarters"},
            ),
        ],
    },
    {
        "folder": "Production Operations",
        "documents": [
            _doc(
                "Shift Handover Log Template and Guide",
                "procedure",
                "Standard template and guidance for documenting open issues, in-process WIP, and "
                "safety notes at every shift change.",
                [
                    "Handover covers open quality holds, equipment status, and staffing notes.",
                    "Outgoing supervisor and incoming supervisor both sign off before shift transition completes.",
                    "Unresolved items from the prior handover must be explicitly carried forward, not dropped.",
                    "Handover logs are retained for 90 days for trend review.",
                ],
                "Grace Liu",
            ),
            _doc(
                "Overall Equipment Effectiveness (OEE) Tracker",
                "tracker",
                "Weekly OEE tracker broken down by availability, performance, and quality components "
                "for each production line.",
                [
                    "Line 2 availability losses are driven primarily by changeover time.",
                    "Performance component is calculated against the ideal cycle time, not the current standard.",
                    "Lines below 75% OEE trigger a root cause review with process engineering.",
                    "OEE trends feed the monthly operations review deck.",
                ],
                "Grace Liu",
                table=[
                    ("Line", "Availability", "Performance", "Quality", "OEE"),
                    ("Line 1", "92%", "88%", "98%", "79%"),
                    ("Line 2", "81%", "90%", "97%", "71%"),
                    ("Line 3", "94%", "91%", "95%", "81%"),
                ],
            ),
            _doc(
                "Preventive Maintenance Schedule - Line 2",
                "tracker",
                "Preventive maintenance task list and interval schedule for critical equipment on "
                "Line 2, used to plan planned downtime windows.",
                [
                    "Lubrication checks on the conveyor drive are performed weekly.",
                    "Full gearbox inspection is scheduled quarterly during planned downtime.",
                    "Missed PM tasks are automatically rolled into the following week's schedule.",
                    "PM compliance rate is reported alongside the monthly OEE review.",
                ],
                "Grace Liu",
            ),
            _doc(
                "Changeover Standard Operating Procedure",
                "procedure",
                "Standardized changeover sequence intended to reduce setup time between product "
                "variants on Assembly Line 1.",
                [
                    "Changeover is split into internal steps (machine stopped) and external steps (prepared in advance).",
                    "Target changeover time is 22 minutes, down from a 35 minute baseline.",
                    "Tooling carts are pre-staged by the prior shift to reduce internal step time.",
                    "Changeover time is logged and reviewed weekly against the target.",
                ],
                "Grace Liu",
            ),
            _doc(
                "Safety Incident Report - Near Miss Forklift Interaction",
                "report",
                "Incident report documenting a near-miss between a forklift and a pedestrian aisle "
                "crossing, with corrective actions.",
                [
                    "Root cause identified limited visibility at the aisle intersection.",
                    "Corrective action added a convex mirror and updated floor marking at the intersection.",
                    "All forklift operators completed a refresher on pedestrian right-of-way rules.",
                    "Follow-up walkthrough scheduled 30 days after corrective actions were implemented.",
                ],
                "Dana Fitzgerald",
            ),
        ],
    },
    {
        "folder": "Supply Chain and Logistics",
        "documents": [
            _doc(
                "Supplier Scorecard - Fastener Components",
                "report",
                "Quarterly scorecard rating the top fastener suppliers on quality, delivery, and "
                "responsiveness metrics.",
                [
                    "On-time delivery is weighted most heavily in the overall supplier score.",
                    "Suppliers scoring below the minimum threshold enter a formal improvement plan.",
                    "Scorecard results are shared directly with each supplier during quarterly business reviews.",
                    "Two suppliers moved from the improvement plan to approved status this quarter.",
                ],
                "Omar Haddad",
                table=[
                    ("Supplier", "Quality Score", "On-Time Delivery", "Overall Rating"),
                    ("Northbridge Fasteners", "96%", "94%", "Preferred"),
                    ("Caldera Supply Co.", "89%", "81%", "Approved"),
                    ("Trimark Components", "78%", "72%", "Improvement Plan"),
                ],
            ),
            _doc(
                "Inventory Cycle Count Procedure",
                "procedure",
                "Describes the rotating cycle count schedule and discrepancy resolution process used "
                "in place of a full annual physical inventory.",
                [
                    "High-value SKUs are counted monthly; low-value SKUs are counted quarterly.",
                    "Discrepancies over 2% of on-hand quantity trigger a root cause investigation.",
                    "Cycle count accuracy is tracked as a monthly KPI reported to the supply chain manager.",
                    "Count adjustments require dual sign-off before the system of record is updated.",
                ],
                "Omar Haddad",
            ),
            _doc(
                "Incoming Materials Service Level Agreement",
                "policy",
                "Defines delivery windows, packaging requirements, and documentation standards "
                "expected from approved raw material suppliers.",
                [
                    "Deliveries outside the scheduled two-hour receiving window require advance notice.",
                    "Certificates of analysis must accompany every lot of regulated raw material.",
                    "Packaging must meet the drop-test and stacking requirements in the supplier handbook.",
                    "Repeated SLA violations are reviewed at the quarterly supplier business review.",
                ],
                "Omar Haddad",
            ),
            _doc(
                "Freight Cost Analysis - Q2",
                "report",
                "Analysis of inbound and outbound freight spend by lane and carrier, identifying cost "
                "reduction opportunities for the upcoming quarter.",
                [
                    "Expedited freight accounted for a disproportionate share of total freight spend.",
                    "Consolidating two weekly less-than-truckload shipments into one reduced cost per unit.",
                    "A regional carrier renegotiation is projected to reduce lane costs by roughly 7%.",
                    "Recommendations are being reviewed with finance before the next carrier contract renewal.",
                ],
                "Omar Haddad",
            ),
            _doc(
                "Supplier Corrective Action Request - Packaging Defect",
                "report",
                "Formal corrective action request issued to a packaging supplier following repeated "
                "damage found during receiving inspection.",
                [
                    "Containment required 100% inspection of incoming lots for the next three shipments.",
                    "Supplier's root cause pointed to an under-specified corner protector on the pallet design.",
                    "Corrective action included an updated pallet packaging specification and drop testing.",
                    "Supplier status remains on the improvement plan pending two clean shipment cycles.",
                ],
                "Omar Haddad",
            ),
        ],
    },
]

MFG_MEETINGS_FOLDER = "Meeting Recordings and Transcripts"
MFG_MEETINGS = [
    _meeting(
        "Line 3 Yield Improvement Weekly Tollgate",
        MFG_MEETINGS_FOLDER,
        [
            (1, "First-pass yield on Line 3 moved up to ninety-two point one percent this week."),
            (2, "That's mostly from the torque spec fix at Station 7, seal leaks are still the biggest remaining category."),
            (0, "What's the plan to tackle the seal leak defects specifically?"),
            (2, "We're trialing a revised gasket seating pressure on two cells starting Monday."),
            (3, "I'll make sure the floor supervisors flag any related quality holds separately so we can isolate the trial data."),
        ],
    ),
    _meeting(
        "Monthly OEE and Downtime Review",
        MFG_MEETINGS_FOLDER,
        [
            (3, "Line 2 OEE came in at seventy-one percent, availability losses are still the biggest driver."),
            (0, "Is that still mostly changeover time, or something new?"),
            (3, "Mostly changeover, though we had one unplanned gearbox stoppage mid-month."),
            (2, "The changeover SOP rollout should help once Line 2 adopts the updated sequence next month."),
            (0, "Let's track changeover time weekly once that rolls out so we can see the impact directly."),
        ],
    ),
    _meeting(
        "Supplier Quarterly Business Review - Fasteners",
        MFG_MEETINGS_FOLDER,
        [
            (4, "Trimark Components is still below the quality threshold, they remain on the improvement plan."),
            (0, "What's their corrective action timeline looking like?"),
            (4, "They've committed to updated inspection records by the end of next month."),
            (1, "If we don't see clean lots by then, we should discuss splitting volume to Northbridge."),
            (4, "Agreed, I'll document that contingency in the scorecard notes."),
        ],
    ),
    _meeting(
        "CAPA Review Board",
        MFG_MEETINGS_FOLDER,
        [
            (1, "CAPA-118 on the label print smearing is still open, what's blocking closure?"),
            (2, "We're waiting on the printhead vendor to confirm the replacement part ships this week."),
            (1, "Let's set a hard follow-up date and escalate if it slips again."),
            (3, "I can confirm the part tracking number and update the log today."),
            (1, "Good, and CAPA-114 on the seal leak is ready to move to verification."),
        ],
    ),
    _meeting(
        "ISO 9001 Internal Audit Planning",
        MFG_MEETINGS_FOLDER,
        [
            (1, "This cycle's audit will focus heavily on document control and training records."),
            (0, "Are we including the new Station 7 work instruction in scope?"),
            (1, "Yes, since it was recently revised it's a good candidate for the audit sample."),
            (2, "I'll make sure the retraining records for that station are ready for the auditors."),
            (1, "Let's finalize the audit schedule and auditee list by Friday."),
        ],
    ),
    _meeting(
        "Safety Committee Monthly Meeting",
        MFG_MEETINGS_FOLDER,
        [
            (5, "The forklift near-miss corrective actions are complete, mirror and floor markings are installed."),
            (0, "Good, let's do a follow-up walkthrough to confirm operators are actually using the new sightlines."),
            (5, "I've scheduled that walkthrough for next week with the shift supervisors."),
            (3, "We should also fold the refresher training completion into the monthly safety scorecard."),
            (5, "Agreed, I'll add that metric starting next report."),
        ],
    ),
    _meeting(
        "Preventive Maintenance Compliance Review",
        MFG_MEETINGS_FOLDER,
        [
            (3, "PM compliance on Line 2 dropped to eighty-six percent this month, mostly missed lubrication checks."),
            (0, "What's causing the lubrication checks to slip?"),
            (3, "Weekend shift coverage has been thin, those checks keep getting deferred."),
            (2, "Let's see if we can shift that task to the weekday shift schedule instead."),
            (3, "I'll update the PM schedule and track compliance again next month."),
        ],
    ),
    _meeting(
        "New Mold Tooling Validation Sign-off",
        MFG_MEETINGS_FOLDER,
        [
            (2, "First article inspection passed all critical dimensions on the new injection mold."),
            (0, "How did the short-run capability study come out?"),
            (2, "Cpk came in at one point four eight on the critical wall thickness dimension."),
            (1, "That clears our threshold, I'm comfortable approving production release."),
            (2, "I'll finalize the preventive maintenance plan for the new tool before we schedule the first run."),
        ],
    ),
    _meeting(
        "Line Balancing Pilot Review - Assembly Line 2",
        MFG_MEETINGS_FOLDER,
        [
            (2, "The pilot moving one sub-assembly step to Station 3 brought the bottleneck within two seconds of takt."),
            (3, "Operators adapted quickly, no complaints on the new station layout."),
            (0, "Let's extend the pilot for one more week before making it permanent."),
            (2, "I'll track throughput daily and bring final numbers to next week's review."),
            (0, "If it holds, let's plan the rollout to Line 1 as well."),
        ],
    ),
    _meeting(
        "Freight Cost Reduction Working Session",
        MFG_MEETINGS_FOLDER,
        [
            (4, "Expedited freight is still a disproportionate share of spend, mostly driven by late supplier releases."),
            (0, "Is that concentrated with one or two suppliers specifically?"),
            (4, "Mostly the fastener and packaging categories, both of which have ongoing corrective actions already."),
            (4, "The lane consolidation change is projected to save around seven percent once implemented."),
            (0, "Let's time the carrier renegotiation with the contract renewal next quarter."),
        ],
    ),
    _meeting(
        "Incoming Inspection Process Improvement Session",
        MFG_MEETINGS_FOLDER,
        [
            (1, "We're seeing more rejected lots lately, let's check if the sampling plan needs adjusting."),
            (4, "Packaging damage is the top rejection reason, not a dimensional issue."),
            (1, "That lines up with the open supplier corrective action on pallet packaging."),
            (0, "Let's hold off on changing the sampling plan until that corrective action closes out."),
            (1, "Agreed, I'll revisit this once we have two clean shipment cycles from the supplier."),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Sales & Marketing
# ---------------------------------------------------------------------------

SALES_DEPARTMENTS = [
    {
        "folder": "Sales Playbooks",
        "documents": [
            _doc(
                "Discovery Call Guide",
                "procedure",
                "Structured guide for running a first discovery call, including qualifying "
                "questions and the handoff criteria into a technical evaluation.",
                [
                    "Open with business context before diving into current tooling or pain points.",
                    "Qualify budget, timeline, and decision process before scheduling a technical demo.",
                    "Document discovery notes in the CRM within one business day of the call.",
                    "Deals without a confirmed economic buyer by discovery end are flagged for coaching.",
                ],
                "Marcus Lee",
            ),
            _doc(
                "Competitive Battlecard - Northstar Analytics",
                "report",
                "Positioning guide for competing against Northstar Analytics, including common "
                "objections and proof points to use in competitive deals.",
                [
                    "Northstar's strength is reporting; our strength is real-time data freshness.",
                    "Common objection: 'Northstar is cheaper at list price' - counter with total cost of ownership data.",
                    "Win rate against Northstar is highest when a technical evaluation is included.",
                    "Reference customers who switched from Northstar are available through the deal desk.",
                ],
                "Nina Patel",
            ),
            _doc(
                "Objection Handling Guide",
                "procedure",
                "Common objections encountered in the sales cycle with recommended response "
                "frameworks for each.",
                [
                    "Price objections: reframe around total cost of ownership, not list price alone.",
                    "'We already have a solution' objections: ask what's missing in the current tool first.",
                    "Timing objections: propose a smaller pilot scope rather than delaying the full deal.",
                    "Security objections: route directly to the security questionnaire and compliance team.",
                ],
                "Marcus Lee",
            ),
            _doc(
                "Proposal and Pricing Template Guide",
                "procedure",
                "Explains how to assemble a standard proposal, when discounting requires deal desk "
                "approval, and typical proposal turnaround expectations.",
                [
                    "Standard proposals are generated from the approved template in the deal desk portal.",
                    "Discounts above 15% require deal desk approval before the proposal is sent.",
                    "Multi-year proposals require finance review for revenue recognition implications.",
                    "Target proposal turnaround time is 2 business days from request.",
                ],
                "Marcus Lee",
            ),
            _doc(
                "Deal Desk Approval Process",
                "procedure",
                "Describes the approval chain for non-standard terms, including custom contract "
                "language and extended payment terms.",
                [
                    "Non-standard payment terms over 60 days require finance approval.",
                    "Custom legal terms are routed to legal with a 3 business day SLA.",
                    "Deals above a set contract value threshold require VP of Sales sign-off.",
                    "Approved exceptions are logged to inform future template updates.",
                ],
                "Rachel Kim",
            ),
        ],
    },
    {
        "folder": "Marketing Campaigns",
        "documents": [
            _doc(
                "Q3 Campaign Brief - Mid-Market Expansion",
                "deck",
                "Campaign brief outlining the target segment, messaging pillars, and channel mix for "
                "the mid-market expansion push.",
                [
                    "Target segment is mid-market companies with 200-2,000 employees in manufacturing and retail.",
                    "Messaging pillars are speed to value, total cost of ownership, and ease of integration.",
                    "Channel mix includes paid search, targeted LinkedIn ads, and a webinar series.",
                    "Success is measured by marketing qualified leads and pipeline influenced within 90 days.",
                ],
                "Sofia Alvarez",
                metrics={"Target MQLs": "450", "Budget": "$180,000", "Duration": "Q3"},
            ),
            _doc(
                "Content Calendar - Q3",
                "tracker",
                "Editorial calendar tracking planned blog, webinar, and case study content with "
                "owner and publish date.",
                [
                    "Case studies are prioritized from customers with the strongest measurable outcomes.",
                    "Webinar topics are selected based on top inbound content engagement themes.",
                    "Each asset has a designated distribution channel plan before publish date.",
                    "Underperforming content categories are reviewed and deprioritized quarterly.",
                ],
                "Sofia Alvarez",
                table=[
                    ("Asset", "Type", "Owner", "Publish Date"),
                    ("Faster Onboarding Case Study", "Case Study", "Sofia Alvarez", "2026-08-05"),
                    ("Total Cost of Ownership Webinar", "Webinar", "Marcus Lee", "2026-08-19"),
                    ("Integration Best Practices Blog", "Blog", "Sofia Alvarez", "2026-09-02"),
                ],
            ),
            _doc(
                "Lead Scoring Model Overview",
                "report",
                "Documents the scoring criteria that qualify a marketing lead as sales-ready, "
                "combining firmographic and engagement signals.",
                [
                    "Firmographic fit contributes up to 40 points based on company size and industry.",
                    "Engagement signals such as webinar attendance and pricing page visits add up to 60 points.",
                    "Leads scoring above 70 points are routed to sales development within one business day.",
                    "Scoring weights are reviewed quarterly against actual conversion data.",
                ],
                "Sofia Alvarez",
            ),
            _doc(
                "Webinar Recap Report - Total Cost of Ownership Series",
                "report",
                "Post-event report summarizing attendance, engagement, and pipeline influenced by the "
                "total cost of ownership webinar series.",
                [
                    "Registration-to-attendance rate was 58%, above the quarterly average of 48%.",
                    "Top engagement question concerned implementation timeline versus competitors.",
                    "Twelve attendees were existing open opportunities, fast-tracked to late-stage discussion.",
                    "Recording was repurposed into three short clips for paid social distribution.",
                ],
                "Sofia Alvarez",
            ),
            _doc(
                "Brand and Messaging Guidelines",
                "policy",
                "Defines approved brand voice, visual identity rules, and messaging pillars for all "
                "external-facing marketing materials.",
                [
                    "Brand voice is direct, confident, and avoids unnecessary jargon.",
                    "Primary and secondary logo usage rules are defined with minimum clear space requirements.",
                    "Messaging pillars must be referenced in any new campaign brief before launch.",
                    "All external materials go through brand review before publishing.",
                ],
                "Sofia Alvarez",
            ),
        ],
    },
    {
        "folder": "Customer Success",
        "documents": [
            _doc(
                "Customer Onboarding Playbook",
                "procedure",
                "Step-by-step onboarding plan for new customers from contract signature through "
                "first value milestone.",
                [
                    "Kickoff call is scheduled within 3 business days of contract signature.",
                    "First value milestone target is 30 days from kickoff for standard implementations.",
                    "Technical onboarding includes a dedicated integration checklist per customer environment.",
                    "Handoff to the ongoing success manager happens after the first value milestone is reached.",
                ],
                "Tom Bergstrom",
            ),
            _doc(
                "Quarterly Business Review Template and Guide",
                "procedure",
                "Template and facilitation guide for the quarterly business review conducted with "
                "strategic accounts.",
                [
                    "QBR covers usage trends, adoption gaps, and upcoming roadmap relevant to the account.",
                    "Success manager prepares an account health summary before the meeting, not during it.",
                    "Expansion opportunities identified in the QBR are logged directly to the account plan.",
                    "Action items from the QBR are followed up on within 5 business days.",
                ],
                "Tom Bergstrom",
            ),
            _doc(
                "Churn Risk Scorecard",
                "tracker",
                "Scorecard combining usage decline, support ticket volume, and renewal timing to flag "
                "accounts at risk of churning.",
                [
                    "Usage decline of more than 25% month over month is the strongest single risk signal.",
                    "Accounts flagged high-risk are reviewed in the weekly customer success leadership sync.",
                    "Save plays are documented per account, not applied generically.",
                    "Outcomes of save plays feed back into refining the scorecard weighting.",
                ],
                "Tom Bergstrom",
                table=[
                    ("Account", "Usage Trend", "Open Tickets", "Risk Level"),
                    ("Harborview Logistics", "Down 31%", "4", "High"),
                    ("Prairie Foods Co.", "Flat", "1", "Low"),
                    ("Summit Retail Group", "Down 12%", "2", "Medium"),
                ],
            ),
            _doc(
                "Renewal Playbook",
                "procedure",
                "Outlines the renewal timeline, discounting guardrails, and escalation path for "
                "at-risk renewals.",
                [
                    "Renewal conversations begin 120 days before contract end date.",
                    "Discounting on renewals above 10% requires VP of Sales approval.",
                    "At-risk renewals are flagged to the churn risk scorecard for cross-team visibility.",
                    "Multi-year renewal incentives are offered only through the approved renewal template.",
                ],
                "Tom Bergstrom",
            ),
            _doc(
                "NPS Survey Summary - Q2",
                "report",
                "Summary of the quarterly Net Promoter Score survey results, including verbatim "
                "themes from detractor responses.",
                [
                    "Overall NPS came in at 42, up four points from the prior quarter.",
                    "Detractor comments most frequently cited reporting flexibility as a gap.",
                    "Promoter comments consistently highlighted implementation speed as a strength.",
                    "Findings were shared with product management for the next roadmap planning cycle.",
                ],
                "Tom Bergstrom",
                metrics={"NPS": "42", "Response rate": "34%", "Promoters": "58%"},
            ),
        ],
    },
    {
        "folder": "Competitive Intelligence",
        "documents": [
            _doc(
                "Competitor Teardown - Northstar Analytics",
                "report",
                "Detailed teardown of Northstar Analytics' product, pricing, and go-to-market "
                "positioning based on public sources and win-loss interviews.",
                [
                    "Northstar's pricing is tiered by seat count rather than usage volume.",
                    "Their go-to-market emphasizes enterprise reporting and governance features.",
                    "Public reviews most frequently cite slow data refresh as a weakness.",
                    "Teardown is refreshed quarterly or after any major competitor product announcement.",
                ],
                "Nina Patel",
            ),
            _doc(
                "Win-Loss Analysis - Q2",
                "report",
                "Analysis of closed-won and closed-lost deals from the quarter, highlighting the top "
                "reasons cited for each outcome.",
                [
                    "Top win reason cited was implementation speed compared to incumbent tools.",
                    "Top loss reason cited was price relative to a lower-cost competitor option.",
                    "Deals with a technical evaluation included had a measurably higher win rate.",
                    "Findings were shared with sales enablement to update the objection handling guide.",
                ],
                "Nina Patel",
            ),
            _doc(
                "Market Positioning Brief",
                "deck",
                "Summarizes the competitive landscape and recommended positioning statement for "
                "the current fiscal year.",
                [
                    "Three primary competitors are tracked across pricing, features, and market presence.",
                    "Recommended positioning emphasizes real-time data freshness and integration breadth.",
                    "Positioning brief is reviewed with sales leadership before each fiscal year planning cycle.",
                    "Messaging updates from this brief flow into the brand and messaging guidelines.",
                ],
                "Nina Patel",
            ),
            _doc(
                "Pricing Comparison Analysis",
                "tracker",
                "Side-by-side pricing comparison across the top three competitors at comparable "
                "usage tiers.",
                [
                    "Comparison normalizes pricing to a per-seat-per-month equivalent for consistency.",
                    "Entry-tier pricing is competitive; enterprise-tier pricing is positioned at a premium.",
                    "Analysis is updated whenever a competitor publicly changes list pricing.",
                    "Results are used directly in the competitive battlecards.",
                ],
                "Nina Patel",
                table=[
                    ("Competitor", "Entry Tier", "Mid Tier", "Enterprise Tier"),
                    ("Northstar Analytics", "$29/seat", "$59/seat", "Custom"),
                    ("Velocity Insights", "$35/seat", "$65/seat", "Custom"),
                    ("Our Platform", "$32/seat", "$62/seat", "Custom"),
                ],
            ),
        ],
    },
]

SALES_MEETINGS_FOLDER = "Meeting Recordings and Transcripts"
SALES_MEETINGS = [
    _meeting(
        "Pipeline Coverage Review - West Region",
        SALES_MEETINGS_FOLDER,
        [
            (5, "West region coverage is sitting at two point one times quota for next quarter, a bit thin."),
            (0, "Which stage is the biggest gap, early pipeline or late stage?"),
            (5, "Early pipeline specifically, we need more qualified discovery calls booked this month."),
            (1, "I can share the updated discovery call guide with the team again as a refresher."),
            (0, "Let's also check if marketing has a campaign that can drive more inbound volume to the region."),
        ],
    ),
    _meeting(
        "Mid-Market Expansion Campaign Kickoff",
        SALES_MEETINGS_FOLDER,
        [
            (2, "The mid-market campaign targets manufacturing and retail accounts with two hundred to two thousand employees."),
            (0, "What's the handoff process for leads that score above the sales-ready threshold?"),
            (2, "Those route directly to sales development within one business day automatically."),
            (1, "Let's make sure reps know the messaging pillars so follow-up calls stay consistent."),
            (2, "I'll share the campaign brief with the full sales team before launch next week."),
        ],
    ),
    _meeting(
        "Competitive Win-Loss Debrief",
        SALES_MEETINGS_FOLDER,
        [
            (4, "This quarter's win-loss data shows implementation speed as the top reason we win deals."),
            (0, "And price is still the top reason we lose, correct?"),
            (4, "Yes, specifically against lower-cost competitors at the entry tier."),
            (1, "That lines up with what we're seeing in the field, the objection handling guide should reflect it."),
            (4, "I'll update the guide and share the refreshed battlecard with the team this week."),
        ],
    ),
    _meeting(
        "Deal Desk Exception Review",
        SALES_MEETINGS_FOLDER,
        [
            (0, "We have three deals requesting payment terms beyond our standard sixty days this week."),
            (1, "Two are renewals and one is a new logo, the new logo deal is also requesting a larger discount."),
            (0, "Let's review the new logo deal first since it needs both finance and VP approval."),
            (1, "I'll get the paperwork routed today so we don't slip the quarter-end close."),
            (0, "Agreed, let's also log these exceptions so we can see if the standard terms need revisiting."),
        ],
    ),
    _meeting(
        "Quarterly Business Review Prep - Strategic Accounts",
        SALES_MEETINGS_FOLDER,
        [
            (3, "Harborview Logistics usage is down thirty-one percent, that account needs a save play before the QBR."),
            (0, "What's driving the usage decline specifically?"),
            (3, "A champion change on their side, the new stakeholder hasn't been onboarded to the reporting features yet."),
            (3, "I'm scheduling a dedicated enablement session with them before the QBR."),
            (0, "Good, let's flag that account specifically in this week's leadership sync."),
        ],
    ),
    _meeting(
        "Renewal Pipeline Review",
        SALES_MEETINGS_FOLDER,
        [
            (3, "We have four renewals entering the hundred twenty day window this month."),
            (0, "Any of them showing churn risk signals already?"),
            (3, "Summit Retail Group is medium risk, usage is down twelve percent but tickets are low."),
            (3, "I'll start renewal conversations early on that one given the usage trend."),
            (0, "Let's keep the others on the standard renewal timeline for now."),
        ],
    ),
    _meeting(
        "Webinar Series Performance Review",
        SALES_MEETINGS_FOLDER,
        [
            (2, "The total cost of ownership webinar series had a fifty-eight percent attendance rate, above average."),
            (0, "Did we see any existing open opportunities attend?"),
            (2, "Twelve open opportunities attended and were fast-tracked into late-stage discussion."),
            (5, "I'll follow up directly with the reps on those twelve accounts this week."),
            (2, "I'm repurposing the recording into short clips for paid social next."),
        ],
    ),
    _meeting(
            "NPS Survey Results Readout",
            SALES_MEETINGS_FOLDER,
            [
                (3, "Overall NPS came in at forty-two this quarter, up four points from last quarter."),
                (0, "What's driving the improvement, do we know?"),
                (3, "Promoter comments consistently cite implementation speed as the strength."),
                (4, "Detractors still mention reporting flexibility as a gap, which lines up with the competitive teardown."),
                (0, "Let's make sure product management sees both the NPS themes and the teardown findings together."),
            ],
        ),
        _meeting(
            "Market Positioning Brief Review",
            SALES_MEETINGS_FOLDER,
            [
                (4, "I'm proposing we lean harder into data freshness as the primary positioning pillar this year."),
                (0, "How confident are we that resonates in competitive deals specifically?"),
                (4, "Win-loss data supports it, it's cited often when we win against Northstar."),
                (1, "If we shift positioning, the objection handling guide and battlecards both need updates."),
                (4, "I'll coordinate those updates once the brief is finalized."),
            ],
        ),
        _meeting(
            "Discovery Call Coaching Session",
            SALES_MEETINGS_FOLDER,
            [
                (1, "I want to review a few recent discovery calls where we didn't confirm an economic buyer."),
                (5, "Two of mine fall into that category, I moved too quickly into the demo."),
                (1, "Let's slow that down, qualifying budget and decision process should come before scheduling a demo."),
                (5, "Understood, I'll use the discovery guide checklist more deliberately on the next set of calls."),
                (1, "Let's revisit these specific deals again next week and see if qualification improved."),
            ],
        ),
        _meeting(
            "Brand Guidelines Refresh Review",
            SALES_MEETINGS_FOLDER,
            [
                (2, "We're proposing a small refresh to the brand guidelines, mainly around the secondary color palette."),
                (0, "Does this affect any in-flight campaign assets?"),
                (2, "Only the mid-market expansion campaign, which hasn't gone to design production yet."),
                (2, "I'll make sure that campaign uses the updated guidelines once they're approved."),
                (0, "Let's get final sign-off by the end of the week so we don't delay the campaign."),
            ],
        ),
        _meeting(
            "Churn Risk Review - Leadership Sync",
            SALES_MEETINGS_FOLDER,
            [
                (0, "Harborview Logistics remains our highest risk account, usage is still down significantly."),
                (3, "The save play enablement session is scheduled for next week with their new stakeholder."),
                (0, "Let's treat that as the deciding factor before we discuss any contract concessions."),
                (3, "Agreed, I'll report back on engagement right after the session."),
                (0, "Let's also double check if any other accounts are trending toward the high-risk threshold."),
            ],
        ),
]


SITE_DATA = {
    "hr": {"departments": HR_DEPARTMENTS, "meetings_folder": HR_MEETINGS_FOLDER, "meetings": HR_MEETINGS},
    "manufacturing": {"departments": MFG_DEPARTMENTS, "meetings_folder": MFG_MEETINGS_FOLDER, "meetings": MFG_MEETINGS},
    "sales": {"departments": SALES_DEPARTMENTS, "meetings_folder": SALES_MEETINGS_FOLDER, "meetings": SALES_MEETINGS},
}
