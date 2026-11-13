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
    import os
    for src, dst in ((c.DB_INSURANCE, bc.DB_IIB), (c.DB_REGISTRATION, bc.DB_VAHAN), (c.DB_THEFT_SCRAP, bc.DB_POLICE),
                     (c.DB_CAPTURE, bc.DB_ANPR), (c.DB_MINISTRY, bc.DB_ECHALLAN), (c.DB_DWH, bc.DB_DWH)):
        # Remove the old database's WAL / shared-memory side files first: SQLite would otherwise
        # replay the previous run's pending writes onto the fresh copy and corrupt it.
        for suffix in ("-wal", "-shm"):
            if os.path.exists(dst + suffix):
                os.remove(dst + suffix)
        shutil.copy(src, dst)
    print("  [✓] Microservice databases synced.")

    print("\n[6/6] Building data-quality store and evaluating plate-matching algorithms (~40s)...")
    import os
    from matching import store
    from matching.evaluation import run_evaluation, evaluate_cleansing
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(bc.DB_DATA_QUALITY + suffix):
            os.remove(bc.DB_DATA_QUALITY + suffix)
    store.init_store(bc.DB_DATA_QUALITY)
    index = store.load_reference_index_all_sources()
    staged = store.seed_noisy_records(bc.DB_DATA_QUALITY, index)
    report = run_evaluation([v["plate"] for v in index])
    report["cleansing"] = evaluate_cleansing(store.list_noisy_records(bc.DB_DATA_QUALITY), index)
    store.save_evaluation(bc.DB_DATA_QUALITY, report)
    best = report["methods"][report["selected_method"]]
    print(f"  [✓] {staged} noisy records staged for cleansing.")
    print(f"  [✓] Best method: {best['label']} (F1 {best['f1']:.3f} at threshold {best['best_threshold']:.2f}).")

    from backend import security
    if not security.configured():
        print("\n[!] Security is not configured on this laptop (no FEDERATION_SECRET in .env).")
        print("    First laptop:  python -m backend.security init-env   (prints the login passwords once)")
        print("    Other laptops: copy that same .env file into this folder.")

    print("\nSetup complete. Next steps:")
    print("  python3 start_system.py # launch the distributed web app + microservices")
    print("  pytest                  # run the automated test suite")


if __name__ == "__main__":
    main()
