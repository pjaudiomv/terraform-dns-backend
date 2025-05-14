locals {
  lambda_url = "https://${aws_lambda_function_url.this.url_id}.lambda-url.us-east-1.on.aws"
}

output "lambda_url" {
  value = local.lambda_url
}

resource "local_file" "this" {
  filename = "${path.module}/example/main.tf"
  content  = <<EOT
terraform {
  backend "http" {
    address        = "${local.lambda_url}/default/default/example.tfstate"
    lock_address   = "${local.lambda_url}/lock/default/example.tfstate"
    unlock_address = "${local.lambda_url}/unlock/default/example.tfstate"
    username       = "${var.tf_backend_username}"
    password       = "${var.tf_backend_password}"
    lock_method    = "POST"
    unlock_method  = "POST"
  }
}

output "uuid" {
  value = base64sha256("hello world")
}
EOT
}
