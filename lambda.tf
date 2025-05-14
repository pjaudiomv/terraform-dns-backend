data "archive_file" "this" {
  type        = "zip"
  source_dir  = "${path.module}/lambda_function"
  output_path = "${path.module}/lambda.zip"
}

resource "aws_lambda_function" "this" {
  function_name    = "terraform-dns-backend"
  role             = aws_iam_role.this.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.11"
  filename         = data.archive_file.this.output_path
  source_code_hash = data.archive_file.this.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      TF_BACKEND_USERNAME       = var.tf_backend_username
      TF_BACKEND_PASSWORD       = var.tf_backend_password
      TF_BACKEND_HOSTED_ZONE_ID = var.hosted_zone_id
      TF_BACKEND_DOMAIN_NAME    = var.domain_name
      TF_BACKEND_DOMAIN_PREFIX  = var.domain_prefix
    }
  }
}

resource "aws_lambda_function_url" "this" {
  function_name      = aws_lambda_function.this.function_name
  authorization_type = "NONE"
}
