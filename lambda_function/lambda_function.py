import json
import uuid
import boto3
import base64
import hashlib
import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("terraform-route53-backend")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

USERNAME = os.environ.get("TF_BACKEND_USERNAME")
PASSWORD = os.environ.get("TF_BACKEND_PASSWORD")
HOSTED_ZONE_ID = os.environ.get("TF_BACKEND_HOSTED_ZONE_ID")
DOMAIN_PREFIX = os.environ.get("TF_BACKEND_DOMAIN_PREFIX", "terraform-state")
DOMAIN_NAME = os.environ.get("TF_BACKEND_DOMAIN_NAME", "example.org")
MAX_TXT_LENGTH = 255

route53 = boto3.client('route53')


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")
    try:
        path = event.get('rawPath', '')
        method = event.get('requestContext', {}).get('http', {}).get('method', '')
        headers = event.get('headers', {}) or {}
        body = event.get('body', '')
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode()
        query = event.get('queryStringParameters') or {}

        if not check_auth(headers):
            return respond(401, {"message": "Unauthorized"}, headers={"WWW-Authenticate": "Basic"})

        if path == "/health":
            return respond(200, {"status": "healthy"})

        parts = path.strip("/").split("/")
        if len(parts) < 2:
            return respond(400, {"message": "Missing path or workspace"})

        route = parts[0]
        workspace = parts[1]
        path_param = "/".join(parts[2:])

        record_name = get_record_name(workspace, path_param)

        if route == "lock":
            if method in ["LOCK", "POST"]:
                return lock(record_name, body)
        elif route == "unlock":
            if method in ["UNLOCK", "POST"]:
                return unlock(record_name, body)
        elif method == "GET":
            return get_state(record_name)
        elif method == "POST":
            return update_state(workspace, path_param, body, query)
        elif method == "DELETE":
            return delete_state(record_name)
        else:
            return respond(405, {"message": "Method Not Allowed"})

    except Exception as e:
        logger.exception("Unhandled exception")
        return respond(500, {"message": str(e)})


def check_auth(headers):
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        return False
    decoded = base64.b64decode(auth[6:]).decode()
    username, password = decoded.split(":", 1)
    return username == USERNAME and password == PASSWORD


def respond(status_code, body, headers=None):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            **(headers or {})
        },
        "body": json.dumps(body),
    }


def get_record_name(workspace, path):
    path_hash = hashlib.md5(path.encode()).hexdigest()[:8]
    name = f"{DOMAIN_PREFIX}.{path_hash}" if workspace == "default" else f"{DOMAIN_PREFIX}.{workspace}.{path_hash}"
    return f"{name}.{DOMAIN_NAME}."


def split_state_for_txt(state_data):
    encoded_data = base64.b64encode(state_data.encode()).decode()
    return [encoded_data[i:i + MAX_TXT_LENGTH] for i in range(0, len(encoded_data), MAX_TXT_LENGTH)]


def store_state_in_route53(record_name, state_data):
    try:
        chunks = split_state_for_txt(state_data)
        resource_records = [{"Value": f'"{chunk}"'} for chunk in chunks]
        route53.change_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            ChangeBatch={
                "Comment": "Terraform state update",
                "Changes": [{
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": record_name,
                        "Type": "TXT",
                        "TTL": 300,
                        "ResourceRecords": resource_records,
                    }
                }]
            }
        )
        return True
    except Exception as e:
        logger.error(f"Failed to store state: {e}")
        return False


def get_state_from_route53(record_name: str, return_none_if_not_found=False) -> Optional[str]:
    try:
        response = route53.list_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            StartRecordName=record_name,
            StartRecordType='TXT',
            MaxItems='1'
        )

        if (response['ResourceRecordSets'] and
                response['ResourceRecordSets'][0]['Name'] == record_name and
                response['ResourceRecordSets'][0]['Type'] == 'TXT'):
            txt_values = []
            for record in response['ResourceRecordSets'][0]['ResourceRecords']:
                value = record['Value']
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                txt_values.append(value)
            combined_data = ''.join(txt_values)
            decoded_data = base64.b64decode(combined_data.encode()).decode()
            return decoded_data

        if return_none_if_not_found:
            return None

    except Exception as e:
        logger.error(f"Failed to get state from Route53: {str(e)}")

    if return_none_if_not_found:
        return None

    return json.dumps({
        "version": 4,
        "terraform_version": "1.8.4",
        "serial": 0,
        "lineage": str(uuid.uuid4()),
        "outputs": {},
        "resources": []
    })


def delete_state_in_route53(record_name):
    try:
        resp = route53.list_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            StartRecordName=record_name,
            StartRecordType="TXT",
            MaxItems="1"
        )
        if not resp["ResourceRecordSets"]:
            return True
        route53.change_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            ChangeBatch={
                "Comment": "Terraform state delete",
                "Changes": [{
                    "Action": "DELETE",
                    "ResourceRecordSet": resp["ResourceRecordSets"][0]
                }]
            }
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to delete: {e}")
        return False


def lock(record_name, body):
    existing = get_lock_from_route53(record_name)
    if existing:
        try:
            parsed = {
                "ID": existing.get("ID", ""),
                "Operation": existing.get("Operation", ""),
                "Info": existing.get("Info", ""),
                "Who": existing.get("Who", ""),
                "Version": existing.get("Version", ""),
                "Created": existing.get("Created", ""),
                "Path": existing.get("Path", "")
            }
        except Exception as e:
            logger.error(f"Failed to parse lock JSON from Route53: {e}")
            parsed = {
                "ID": str(uuid.uuid4()),
                "Operation": "unknown",
                "Info": "failed to parse existing lock",
                "Who": "unknown",
                "Version": "unknown",
                "Created": "",
                "Path": ""
            }

        return respond(423, parsed)

    success = store_state_in_route53(f"lock.{record_name}", body)
    if success:
        return respond(200, {"message": "Lock acquired"})
    else:
        return respond(500, {"message": "Failed to acquire lock"})


def unlock(record_name, body):
    lock_id = None
    if body.strip():
        try:
            request_lock = json.loads(body)
            lock_id = request_lock.get("ID")
        except Exception as e:
            logger.error(f"Failed to parse unlock JSON: {e}")
            return respond(400, {"message": "Invalid unlock JSON"})
    else:
        logger.warning("Unlock request had empty body")

    existing = get_lock_from_route53(record_name)
    if existing:
        current_id = existing.get("ID")
        if lock_id and current_id != lock_id:
            logger.warning(f"Unlock failed: lock ID mismatch (expected {current_id}, got {lock_id})")
            return respond(423, existing)

        success = delete_state_in_route53(f"lock.{record_name}")
        if success:
            logger.info(f"Released lock {current_id}")
            return respond(200, {"message": "Lock released"})
        else:
            return respond(500, {"message": "Failed to delete lock"})
    else:
        logger.info("No lock exists to delete")
        return respond(200, {"message": "Nothing to unlock"})


def get_lock_from_route53(record_name: str) -> Optional[dict]:
    lock_record_name = f"lock.{record_name}"
    lock_data = get_state_from_route53(lock_record_name, return_none_if_not_found=True)
    if lock_data:
        try:
            return json.loads(lock_data)
        except Exception as e:
            logger.error(f"Failed to parse lock JSON from Route53: {e}")
    return None


def get_state(record_name):
    data = get_state_from_route53(record_name)
    return respond(200, json.loads(data))


def update_state(workspace, path, body, query):
    record_name = get_record_name(workspace, path)
    logger.info(f"Saving state to record: {record_name}")
    lock_id = query.get("ID")
    if lock_id:
        existing_lock = get_lock_from_route53(record_name)
        if existing_lock and existing_lock.get("ID") != lock_id:
            return respond(423, existing_lock)

    success = store_state_in_route53(record_name, body)
    if success:
        return respond(200, {"message": "State saved"})
    else:
        return respond(500, {"message": "Failed to store state"})


def delete_state(record_name):
    if delete_state_in_route53(record_name):
        return respond(200, {"message": "State deleted"})
    else:
        return respond(500, {"message": "Failed to delete state"})