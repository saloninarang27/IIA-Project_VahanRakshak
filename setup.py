"""
One-shot project setup.

Run: python setup.py

(Re)creates all six databases from schema, seeds all five source databases
with the deterministic fictional dataset, runs the ETL pipeline to build
the data warehouse, and refreshes the materialized-view tables. After this
completes, `streamlit run app.py` and `pytest` are both ready to use.
"""
import db
from seed import seed_capture, seed_insurance, seed_registration, seed_theft_scrap, seed_ministry
from etl.pipeline import run_pipeline
from dwh.refresh_views import refresh_all_views


def main():
    print("\n[1/4] Creating database schemas...")
    db.init_all_schemas()

    print("\n[2/4] Seeding the five independent source databases...")
    seed_capture.seed()
    seed_insurance.seed()
    seed_registration.seed()
    seed_theft_scrap.seed()
    seed_ministry.seed()

    print("\n[3/4] Running ETL pipeline (extract -> transform -> load into DWH)...")
    run_pipeline()

    print("\n[4/4] Refreshing materialized-view tables...")
    refresh_all_views()

    print("\n[5/5] Syncing databases to backend microservice directories...")
    import shutil
    import config as c
    import backend.config as bc
    shutil.copy(c.DB_INSURANCE, bc.DB_IIB)
    shutil.copy(c.DB_REGISTRATION, bc.DB_VAHAN)
    shutil.copy(c.DB_THEFT_SCRAP, bc.DB_POLICE)
    shutil.copy(c.DB_CAPTURE, bc.DB_ANPR)
    shutil.copy(c.DB_MINISTRY, bc.DB_ECHALLAN)
    shutil.copy(c.DB_DWH, bc.DB_DWH)
    print("  [✓] Microservice databases synced.")

    print("\nSetup complete. Next steps:")
    print("  python3 start_system.py # launch the distributed web app + microservices")
    print("  pytest                  # run the automated test suite")


if __name__ == "__main__":
    main()
