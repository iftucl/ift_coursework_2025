import subprocess

from apscheduler.schedulers.blocking import BlockingScheduler


def my_scheduled_task():
    print("--- Triggering Scheduled Production Run ---")
    # Your update_momentum_data(df) logic goes here
    subprocess.run(["poetry", "run", "python", "main.py"])


if __name__ == "__main__":
    scheduler = BlockingScheduler()

    # This tells the script: "Every day at 18:00 (6 PM), run the function above"
    scheduler.add_job(my_scheduled_task, "cron", hour=18, minute=0)

    print("System is LIVE. Press Ctrl+C to exit.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped manually.")
