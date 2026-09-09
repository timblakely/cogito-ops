variable "access_token" {
  description = "Matrix access token supplied by External Secrets from 1Password."
  type        = string
  sensitive   = true
}

provider "matrix" {
  homeserver_url = "https://matrix.timblakely.com"
  access_token   = var.access_token
  user_id        = "@agent-gitops:matrix.timblakely.com"
}

data "matrix_whoami" "controller" {}
