#!/usr/bin/env python3
import imaplib
import email
from email.header import decode_header
import json
import os
import tempfile
import traceback
import time
import logging
from typing import Dict, Any, Optional
import requests

CONFIG_PATH = "config.json"
STATE_FILE = "state.json"
FAILED_STATE_FILE = "failed_state.json"

API_UPLOAD_URL = "https://toplabsbazaardev-git-development-pratiks-projects-7c12a0c0.vercel.app/booking-services/upload-report"

# ---------- LOGGING SETUP ----------
logging.basicConfig(
    filename="mail_processor.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console.setFormatter(formatter)
logging.getLogger().addHandler(console)

# ---------- HELPERS ----------
def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logging.exception(f"Error loading {path}")
        return default

def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logging.exception(f"Error saving {path}")

def load_config(path: str) -> Dict[str, Any]:
    return load_json(path, {})

def load_state() -> set:
    return set(load_json(STATE_FILE, []))

def save_state(state: set):
    save_json(STATE_FILE, list(state))

def load_failed_state() -> set:
    return set(load_json(FAILED_STATE_FILE, []))

def save_failed_state(state: set):
    save_json(FAILED_STATE_FILE, list(state))

def decode_str(s: Optional[bytes]) -> str:
    if not s:
        return ""
    if isinstance(s, str):
        return s
    try:
        parts = decode_header(s)
        pieces = []
        for part, enc in parts:
            if isinstance(part, bytes):
                pieces.append(part.decode(enc or "utf-8", errors="ignore"))
            else:
                pieces.append(part)
        return "".join(pieces)
    except Exception:
        return str(s)

def get_filename_from_part(part) -> str:
    fname = part.get_filename()
    return decode_str(fname) if fname else ""

# ---------- UPLOAD WITH RETRY ----------
def upload_report_to_api(file_path: str, patient_name: str, max_retries=3) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, "application/pdf")}
                data = {"patientName": patient_name}
                response = requests.post(API_UPLOAD_URL, files=files, data=data, timeout=20)

            if response.status_code == 200:
                logging.info(f"[UPLOAD ✅] {file_path} for '{patient_name}'")
                return True
            else:
                logging.warning(f"[UPLOAD ❌ Attempt {attempt}] {response.status_code}: {response.text}")
        except Exception as e:
            logging.error(f"[UPLOAD ❌ Attempt {attempt}] Error: {e}")

        time.sleep(3)  # backoff between retries

    logging.error(f"[UPLOAD FAILED 🚫] Gave up after {max_retries} attempts for '{patient_name}' ({file_path})")
    return False

# ---------- MAIN PROCESSING ----------
def process_account(account: Dict[str, Any], processed_ids: set, failed_ids: set):
    name = account.get("name") or account["email"]
    imap_server = account["imap_server"]
    imap_port = account.get("imap_port", 993)
    user = account["email"]
    password = account["password"]

    logging.info(f"[{name}] Connecting to {imap_server} ...")
    try:
        imap = imaplib.IMAP4_SSL(imap_server, imap_port)
        imap.login(user, password)
    except Exception as e:
        logging.error(f"[{name}] IMAP login failed: {e}")
        return

    try:
        imap.select("INBOX")
        result, data = imap.uid("search", None, "ALL")
        if result != "OK":
            logging.error(f"[{name}] UID search failed")
            imap.logout()
            return

        uids = sorted([int(x) for x in data[0].split()], reverse=True)
        latest_uids = uids[:10]

        for uid in latest_uids:
            try:
                res, msg_data = imap.uid("fetch", str(uid), "(RFC822)")
                if res != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                message_id = msg.get("Message-ID") or str(uid)

                if message_id in processed_ids:
                    continue

                frm = decode_str(msg.get("From", ""))
                subject = decode_str(msg.get("Subject", ""))
                logging.info(f"[{name}] UID {uid} | From: {frm} | Subject: {subject}")

                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    filename = get_filename_from_part(part)
                    if not filename.lower().endswith(".pdf"):
                        continue

                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    with tempfile.NamedTemporaryFile(prefix="rep_", suffix=".pdf", delete=False) as tf:
                        tf.write(payload)
                        temp_path = tf.name

                    try:
                        from name_extractor import extract_patient_name
                        res_name = extract_patient_name(temp_path, original_filename=filename)
                        extracted_name = res_name[0] if isinstance(res_name, tuple) else res_name

                        logging.info(f"[{name}] '{filename}' -> '{extracted_name}'")

                        success = upload_report_to_api(temp_path, extracted_name)
                        if success:
                            processed_ids.add(message_id)
                        else:
                            failed_ids.add(message_id)

                    except Exception as ex_proc:
                        logging.exception(f"[{name}] Error processing {filename}: {ex_proc}")
                        failed_ids.add(message_id)
                    finally:
                        try:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception:
                            logging.warning(f"[CLEANUP ❌] {temp_path} not deleted")

                imap.uid("store", str(uid), "+FLAGS", "(\\Seen)")

            except Exception as e_item:
                logging.exception(f"[{name}] Error UID {uid}: {e_item}")

        imap.logout()

    except Exception as e_main:
        logging.exception(f"[{name}] Mailbox processing error: {e_main}")
        try:
            imap.logout()
        except Exception:
            pass

# ---------- RUNNER ----------
def main_loop():
    cfg = load_config(CONFIG_PATH)
    interval = cfg.get("poll_interval_seconds", 30)
    processed_ids = load_state()
    failed_ids = load_failed_state()

    logging.info("📬 Mail processor started...")

    try:
        while True:
            for account in cfg.get("accounts", []):
                process_account(account, processed_ids, failed_ids)
            save_state(processed_ids)
            save_failed_state(failed_ids)
            time.sleep(interval)
    except KeyboardInterrupt:
        logging.info("🛑 Graceful shutdown requested. Saving state...")
        save_state(processed_ids)
        save_failed_state(failed_ids)
        logging.info("✅ Shutdown complete.")

if __name__ == "__main__":
    main_loop()
