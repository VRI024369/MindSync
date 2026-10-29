MINDSYNC - PEOPLE, RESEARCHER AND ADMIN PROTOTYPE
=================================================

RUN ON WINDOWS POWERSHELL
1. Extract this ZIP to a folder.
2. Open PowerShell in the MindSync_Advanced folder.
3. Run:
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python app.py
4. Open http://127.0.0.1:5000

LOGIN ROLES
- People: use Register to create a user account. New accounts are People accounts.
- Researcher: use “Create a separate Researcher ID” on the login page, then sign in with the Researcher role.
- Admin demo login: username admin, password admin123. Change this before any non-demo use.
- The login page has a role selector. The selected role must match the account's assigned role.

PEOPLE FEATURES
- Personal details and readings: stress (1-10), current mood, sleep, heart rate, blood pressure, temperature and blood sugar.
- Save multiple readings and download each record as a formatted PDF report.
- Upload existing CSV, PDF or TXT reports. Files are stored locally in uploads/.
- Use Profile & Privacy to manage research consent. Researcher dashboards only include people who opted in.

RESEARCHER FEATURES
- Save researcher profile details.
- Stress trend and mood distribution graphs, plus consented health readings and CSV export.
- Participant labels are pseudonyms. This is not guaranteed anonymization; obtain appropriate ethics approval before real research use.

ADMIN FEATURES
- Manage accounts and assign Researcher roles.
- Upload a numeric EEG CSV dataset for a basic signal-statistics summary.
- Admin dashboard includes stress trend and mood distribution graphs, recent People health readings, a list of uploaded report filenames, account management and EEG dataset upload.
- Review recent health readings and configure email alerts using environment variables below.

OPTIONAL EMAIL ALERT CONFIGURATION
Set these environment variables in the same PowerShell session before starting the app:
$env:MINDSYNC_SMTP_HOST = "smtp.example.com"
$env:MINDSYNC_SMTP_PORT = "587"
$env:MINDSYNC_SMTP_USER = "your-sender@example.com"
$env:MINDSYNC_SMTP_PASSWORD = "your-app-password"
$env:MINDSYNC_SMTP_FROM = "your-sender@example.com"
$env:MINDSYNC_ALERT_TO = "health-alert-recipient@example.com"
python app.py
Use your email provider's app password, not your normal email password. Never share credentials or commit them to source control. If these variables are not configured, high-reading alerts appear on screen but email is not sent.

HEALTH AND SAFETY LIMITATIONS
- This is an academic prototype, not a medical device or emergency monitoring service.
- Thresholds are simple prompts for professional review, not diagnostic rules. Clinical context matters.
- Do not delay medical help while waiting for an email or software report. For severe symptoms or immediate danger, contact local emergency services.
- EEG upload labels are basic rule-based signal demonstrations. They do not reliably determine mood or diagnose mental conditions.
- Keep health data private. Use secure hosting, strong secrets, HTTPS, access controls, backups and appropriate consent/ethics review before deployment with real people.

SEPARATE RESEARCHER REGISTRATION
1. Open the sign-in page and click "Create a separate Researcher ID".
2. Complete the researcher profile and choose a unique Researcher ID and password (minimum 8 characters).
3. Sign in by selecting Researcher and entering those credentials.
4. Researcher accounts are created independently; Admin promotion is not required.

RECOMMENDED USER WORKFLOW
1. Create a People account and complete Profile & Privacy settings.
2. Enter health readings in the Person Details page.
3. Open Reports to review and download the saved reading report.
4. Upload an existing report if needed.
5. Use mood check-ins and support tools; review history and export/delete records as needed.

The health and EEG outputs are demonstrations, not diagnoses. High-reading alerts depend on configured thresholds and SMTP settings; do not rely on this prototype for emergency monitoring.

RESEARCHER WORKSPACE (UPDATED)
- Create a dedicated researcher account from the login page using “Create a separate Researcher ID”.
- Sign in by choosing the Researcher role and entering that Researcher ID and password.
- Save your name, institution, department, research area and email in the Researcher dashboard.
- Researcher dashboard includes consented participant totals, health summaries, Stress Level Trend, Mood Distribution, health-record filters, participant health records, EEG analysis summaries, health CSV export and EEG CSV export.
- The dashboard only includes records belonging to People accounts that have enabled “I consent to my records being included in research exports” under Profile & Privacy and saved the setting. After consenting, the person must submit health readings and/or an EEG analysis for those records to appear.
- An empty dashboard is expected if nobody has consented or no records have been submitted. Researcher accounts do not count as People participants.
- Participant labels are pseudonyms; this is not a guarantee of anonymity. EEG state/score fields are demo outputs, not validated medical or brain-state predictions.

PEOPLE DASHBOARD (REFINED)
- Updated People home screen with a welcome panel, summary metrics, six feature cards, recent health readings, mood check-ins and EEG analysis history.
- Quick links lead to readings, reports, mood support, privacy settings and EEG history.

TESTING NOTES
- Python syntax and Jinja template syntax were checked when this package was prepared.
- Full live Flask route/login tests still need to be run on a computer with the requirements installed. To verify all roles: register a People account; create a separate Researcher account; sign in as admin (admin/admin123); test each role selector and confirm each dashboard opens.
- Recommended end-to-end checks: save a People health record, download its PDF, upload a TXT/PDF/CSV report, enable research consent, confirm the record appears in Researcher analytics under a pseudonymous participant label, and confirm Admin can see the record and uploaded report filename. Also test that Researcher cannot open Admin pages and that a mismatched role selection is rejected.
- Do not use real health data for testing. The seeded admin credentials are for local demonstration only.

FULL UPGRADE ADDITIONS (2026-10-28)
- People dashboard: personal trend chart comparing recent self-reported stress and sleep values.
- Researcher dashboard: exploratory Pearson correlation table for stress/sleep/heart rate, calculated only from consented health records. Correlation is descriptive and does not prove causation.
- Admin dashboard: latest 30 security/activity audit events (login successes/failures, logout, health-record creation, consent changes, EEG analysis, role changes and account deletion where instrumented).
- Existing People, Researcher and Admin routes and roles are retained.

RUN:
1. Extract this ZIP.
2. Open PowerShell in MindSync_Advanced.
3. Run: python -m venv venv
4. Run: .\venv\Scripts\Activate.ps1
5. Run: python -m pip install --upgrade pip
6. Run: python -m pip install -r requirements.txt
7. Run: python app.py
8. Open http://127.0.0.1:5000

Fresh database Admin login: admin / admin123. Use only for local demonstration and change it before any real deployment.
