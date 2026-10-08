# PAUT Workflow Automation

A local Django web app for writing PAUT inspection reports. It reads setup data from
Evident/Olympus `.nde` files, keeps equipment and text libraries, and fills the company's
Word and Excel report templates.

Report types:

- **Long Form**: Word report (`word_templates/paut_master.docx`)
- **Short Form**: Excel corrosion form 598-PAUTFORM-009 (`excel_templates/paut_corrosion.xlsx`)
- **PAUT weld**: Excel weld form (`excel_templates/paut_weld.xlsx`)

Author: Lucas Jennings

## Requirements

- Windows with Microsoft Word and Excel installed (the app drives them to fill the
  templates and make PDFs)
- Python 3.12+

## Setup

```
git clone https://github.com/LucasJen/PAUT-Workflow-Automation.git
cd PAUT-Workflow-Automation
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/.

`migrate` creates `db.sqlite3` and seeds the probe and wedge catalogues, sensitivity blocks
and the text library. The database, uploaded files (`media/`) and generated reports
(`outputs/`) stay on your machine and are not committed.

Optional starting data:

```
python manage.py loaddata equipment/fixtures/equipment.json      # sample scopes and probes
python manage.py loaddata reports/fixtures/saved_setups.json     # sample saved setups
```

## First steps in the app

1. **Preferences > Working folders**: add the folder that holds your job folders for each
   report type. Guided Creation lists jobs from it and saves reports there.
2. **Preferences > Texts and Defaults**: check the method and technique descriptions, and
   set up defaults for each report type (procedure, personnel, equipment that rarely changes).
3. **Equipment**: add your scopes, probes and calibration blocks.
4. **Guided Creation**: pick a job folder; the app reads its `.nde` files and pictures and
   walks through the report section by section, ending at a preview and download.

The Assistant (optional) needs an API key, entered under Preferences > Assistant. The key is
stored encrypted for the current Windows user.

## Useful commands

```
python manage.py test                                   # run the tests
python manage.py import_inventory "<weld workbook>.xlsx" # scopes/probes from a weld report workbook
python manage.py import_catalogue <PATransducers.csv>     # probe/wedge catalogue from Beamtool CSVs
```

Back up `db.sqlite3` before pulling or switching branches.

## Project layout

```
ndt_reports/       Django settings and URLs
reports/           reports, setups, .nde parsing, Word/Excel output, guided creation
equipment/         scopes, probes, wedges, calibration and sensitivity blocks
documents/         procedure, code and training document libraries
assistant/         chat over reports, setups and documents
word_templates/    Word report template
excel_templates/   Excel report templates
```

## Settings

Local use needs no configuration. For a shared server set `DJANGO_DEBUG=0`,
`DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS` (see `ndt_reports/settings.py`).
