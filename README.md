<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=28&pause=800&color=0CF7A5&center=true&vCenter=true&width=700&lines=Sortify+-+AI+Interview+Engine;Dynamic+Follow-up+Questions;Unbiased+Candidate+Evaluation;Detailed+Performance+Reports" width="1200" alt="Typing Animation" />
</p>


# sortify 

A one-on-one AI Interview Engine that is purely unbiased, asks dynamic follow-up questions based on previous responses of the user, and generates detailed performance reports of candidates.


Website Link: https://sortify-ovdv.onrender.com,

##  Features

-  Interactive AI chat interface  (Voice + Text support) 
-  Modular Django application structure
-  SQLite database for lightweight development   
-  Supports local AI model interactions (via Ollama or custom runners)  
-  Preconfigured for Render deployment  
-  Detailed Report Generation after each interview for the candidates to analyse their performance.
-  Dynamic Follow-up questions


---

#  Installation Guide

Follow these steps to run Sortify on your machine from scratch.

##  1. Clone the Repository

```bash
git clone https://github.com/Sortify-sort-knowledge-from-noise/Final_Project.git
cd Final_Project
```

##  2. Create a Python Virtual Environment

A `.venv` ensures your dependencies don't conflict with system packages.

**macOS/Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows**
```bash
python -m venv .venv
.\.venv\Scripts\activate
```

##  Activate Virtual Environment (Every Session)

**macOS/Linux:**
```bash
source .venv/bin/activate
```

**Windows:**
```bash
.\.venv\Scripts\activate
```

##  3. Install Required Dependencies

Make sure your virtual environment is active:

```bash
pip install -r requirements.txt
```

##  Environment Setup

###  4. Create a .env File

Create a `.env` file in the root directory:

**macOS/Linux**
```bash
touch .env
```

**Windows**
```bash
type nul > .env
```

Example `.env` file content:
```ini
DEBUG=True
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///db.sqlite3
```

>  **Never commit your actual .env file to GitHub.**

##  Database Setup

###  5. Apply Migrations

Before running the server, create necessary database tables:

```bash
python manage.py makemigrations
python manage.py migrate
```

SQLite database (`db.sqlite3`) will be created automatically.

##  Run the Application

###  6. Start the Django Development Server

```bash
python manage.py runserver
```

Visit the app at: `http://127.0.0.1:8000/`

---

# Usage Guide

After installation, here's how to work with Sortify on a daily basis:

##  Run the Server

```bash
python manage.py runserver
```

##  Apply New Migrations (When Models Change)

```bash
python manage.py makemigrations
python manage.py migrate
```

## Edit Environment Variables

Modify `.env` anytime you add API keys or new configuration:

```ini
API_KEY=your-api-key
MODEL_PATH=/path/to/model
```

---

#  Render Deployment Notes

Sortify is preconfigured for Render:
- Uses `.render.yaml` for build + deploy steps
- Includes a `releaseCommand` to auto-run migrations on each deploy
- SQLite supported for ephemeral deployments
- If you push updates, Render will rebuild automatically

---

# 👥 Team Members

This project is developed by the following team:
- Shreyas Singh Rajkumar (Backend, ML)
- Abhivyakti Singh (Frontend, Database, Deployment)
- Aryaman Singh (ML, Database, Backend)
- Shreyas Chandrakant Ingle (Frontend, Backend)
- Vansh Rathore (Backend)
- Aryan Tripathi (ML)

---

# 📄 License

This project is intended for academic and educational use.

<br><br>

<p align="center">
  <img src="https://github.com/user-attachments/assets/148a26da-2a2f-4ff1-974f-07a3bd23e3ab" width="250" />
</p>

<br>
<div align="center">

  <h1>© Copyright</h1>

  <p>
    Copyright © 2025 Sortify Team.  
    All rights reserved.
  </p>

</div>
