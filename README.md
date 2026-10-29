# MindSync – Mood and Mental State Monitoring System

## 1. Project Overview

MindSync is a web-based application designed to help users record health-related readings and understand their current mood. The system provides separate dashboards for People, Researchers, and Administrators.

The application supports mood tracking, health data recording, report generation, research data analysis, graphical visualization, and administrative monitoring.

**Note:** MindSync provides experimental mood-related insights and is not a medical diagnostic tool.

## 2. Technologies Used

- Python
- Flask
- HTML and CSS
- JavaScript
- SQLite (if configured in the project)
- Pandas and NumPy (if used in the project)
- Chart.js (if used for graphs)

## 3. Main Modules

### People
- Enter health-related readings.
- Record current mood and sleep duration.
- View mood-related feedback.
- Upload and download reports, if supported by the current version.

### Researcher
- Access the separate researcher dashboard.
- View research-consented participant data.
- Analyze stress trends and mood distribution.
- View graphs and export data, if supported.

### Administrator
- Access the administrative dashboard.
- Manage system users and monitor application activity.
- Upload datasets and review analysis results, if supported.

## 4. Requirements

- Python 3.10 or a compatible version supported by the installed dependencies
- pip
- Git
- A modern web browser

## 5. Installation and Setup

### Step 1: Clone the repository

```bash
git clone https://github.com/YOUR-USERNAME/MindSync.git
cd MindSync
```

Replace `YOUR-USERNAME` with the GitHub account username that owns the repository.

### Step 2: Create a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Step 3: Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### Step 4: Run the application

```powershell
python app.py
```

### Step 5: Open the website

Visit the local URL displayed by Flask, commonly:

http://127.0.0.1:5000/

## 6. Testing

Test the People, Researcher, and Administrator login flows separately. Verify data entry, report handling, dashboard graphs, dataset uploads, and data export according to the features implemented in the current version.

## 7. Project Structure

```text
MindSync/
├── app.py
├── requirements.txt
├── README.md
├── templates/
└── static/
```

Additional files and folders may be present depending on the project version.

## 8. Privacy and Limitations

Use synthetic or anonymized data for demonstrations and research testing. Do not commit passwords, API keys, private databases, or identifiable health information to a public repository.

Mood estimates are experimental and should not be used as a substitute for professional medical assessment.

## 9. Author

MindSync Project Team

Department of Computer Science – AI and Robotics

VIT Chennai
