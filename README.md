# Kellwell-Inventory-Management
An inventory management system that mimics the existing Excel workflow used by employees. Automates the weekly rollover process and allows administrators to quickly view and drill down into financial data.


## Setup

### Prerequisites
- Python 3.x installed
- (PostgreSQL — to be added once we set up the database)

### 1. Clone the repository

```bash
git clone https://github.com/JokerBSRachel/Kellwell-Inventory-Management
cd Kellwell-Inventory-Management
```

### 2. Create and activate a virtual environment

**Create the virtual environment:**

```bash
python3 -m venv venv
```

**Activate it:**
- Windows (PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

- macOS/Linux:

```bash
source venv/bin/activate
```

You should see `(venv)` appear at the beginning of your terminal prompt once activated.

### 3. Install dependencies

```bash
pip install django
```

### 4. Install PostgreSQL

Download and install from [postgresql.org](https://www.postgresql.org/download/windows/).
During installation:
- Set a password for the default `postgres` superuser (you'll need this later)
- Keep the default port (`5432`)
- pgAdmin is included and fine to leave checked; Stack Builder can be skipped/cancelled

**Windows only:** After installing, add PostgreSQL's `bin` folder to your system PATH
(e.g. `C:\Program Files\PostgreSQL\17\bin`), then fully restart VS Code (not just the terminal)
for the change to take effect.

Verify the install:
​
```bash
psql --version​
```

### 5. Create the PostgreSQL database
This is a local version of the database for testing purposes.

Log into PostgreSQL:
​
```bash
psql -U postgres
```
(Enter the password you set during installation)

Create the project database:
​
```sql
CREATE DATABASE kellwell_inventory;
```

Verify it exists:
​
```sql
\l
```

Type `\q` to exit the psql shell.

*(This section will be replaced with `pip install -r requirements.txt` once we generate that file.)*
