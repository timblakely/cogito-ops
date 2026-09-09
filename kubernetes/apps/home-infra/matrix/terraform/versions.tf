terraform {
  required_version = ">= 1.8.0"

  required_providers {
    matrix = {
      source  = "raspbeguy/matrix"
      version = "0.5.0"
    }
  }
}
