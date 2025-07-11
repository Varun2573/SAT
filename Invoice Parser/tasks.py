import os
import json
import psycopg2
from datetime import datetime
from celery import Celery
from invoice_parser import InvoiceParser
from pytz import timezone

IST = timezone('Asia/Kolkata') 

# Environment variables
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "Sat_infotech")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "varun2573")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

# Output folder
OUTPUT_FOLDER = "./output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Setup Celery
celery_app = Celery('tasks', broker=REDIS_URL, backend=REDIS_URL)

# Initialize the parser
parser = InvoiceParser()

def get_pg_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        port=POSTGRES_PORT
    )

def create_table_if_not_exists():
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_acknowledgments (
            id SERIAL PRIMARY KEY,
            task_id TEXT UNIQUE,
            filename TEXT,
            status TEXT,
            result JSONB,
            upload_time TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

create_table_if_not_exists()

@celery_app.task(bind=True, max_retries=5, default_retry_delay=30)
def process_invoice(self, filepath):
    filename = os.path.basename(filepath)
    task_id = self.request.id
    upload_time = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S") 

    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO invoice_acknowledgments (task_id, filename, status, upload_time)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (task_id) DO UPDATE SET
                filename = EXCLUDED.filename,
                status = EXCLUDED.status,
                upload_time = EXCLUDED.upload_time;
        """, (task_id, filename, "Pending", upload_time))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error - Insert] {e}")

    try:
        if filepath.lower().endswith(("pdf", "docx", "txt")):
            result = parser.documentParser(filepath)
        elif filepath.lower().endswith(("jpg", "jpeg", "png", "webp")):
            result = parser.ImageParser(filepath)
        else:
            raise ValueError("Unsupported file type")

        if not result or result == {}:
            raise RuntimeError("Likely API limit reached or empty response.")

        output_path = os.path.join(OUTPUT_FOLDER, f"{os.path.splitext(filename)[0]}_{task_id}.json")
        with open(output_path, 'w') as json_file:
            json.dump(result, json_file, indent=2)

        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE invoice_acknowledgments
            SET status = %s, result = %s
            WHERE task_id = %s;
        """, ("Completed", json.dumps(result), task_id))
        conn.commit()
        cur.close()
        conn.close()

        print(f"[DB] Updated status to Completed for {task_id}")
        return result

    except RuntimeError as e:
        print(f"[Retry Triggered] {e}")
        raise self.retry(exc=e)

    except Exception as e:
        print(f"[Task Error] {e}")
        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE invoice_acknowledgments
            SET status = %s
            WHERE task_id = %s;
        """, ("Rejected", task_id))
        conn.commit()
        cur.close()
        conn.close()
        return None

