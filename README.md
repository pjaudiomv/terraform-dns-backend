# Terraform DNS Backend

This project provides a custom [HTTP backend](https://developer.hashicorp.com/terraform/language/backend/http) for Terraform that stores state files as DNS TXT records in AWS Route 53.

Tired of using S3 with *only* nine 9s of reliability? Store your Terraform state in one of the most globally distributed systems on the planet: DNS.

---

## 🛠 How It Works

1. The backend is a Python-based AWS Lambda function that implements the Terraform HTTP backend protocol.
2. When Terraform fetches state, the service retrieves base64-encoded chunks from DNS TXT records.
3. When Terraform writes state, the service splits and stores the state across TXT records.
4. DNS record size limits are respected by splitting state data into 255-byte chunks.
5. State locking is supported via dedicated `TXT` records prefixed with `lock.`.
6. Authentication is enforced via HTTP Basic Auth.

---

## 🔧 Architecture

- **AWS Lambda Function** – Serves Terraform backend endpoints (`GET`, `POST`, `DELETE`)
- **AWS Route 53** – Stores Terraform state and lock data as DNS TXT records

---

## 🚀 Deployment

### 1. Create a `terraform.tfvars` File

```hcl
domain_name         = "yourdomain.com"
domain_prefix       = "terraform-state"
hosted_zone_id      = "Z1234567890ABC"
tf_backend_username = "thisisnota"
tf_backend_password = "dumpsterfire"
```

## ⚙️ Using the Backend

An example/main.tf file is automatically generated to demonstrate how to configure a Terraform project to use the Route 53-based backend via the deployed Lambda function.

```hcl
terraform {
  backend "http" {
    address = "https://lambda.function.url/default/my-project"
    lock_address = "https://lambda.function.url/lock/default/my-project"
    unlock_address = "https://lambda.function.url/unlock/default/my-project"
    username = "your-username"
    password = "your-password"
    lock_method    = "POST"
    unlock_method  = "POST"
  }
}
```
