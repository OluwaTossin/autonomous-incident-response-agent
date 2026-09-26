resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public HTTPS ingress to AIRA"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.common_tags, { component = "load-balancer" })
}
resource "aws_vpc_security_group_ingress_rule" "alb_http_ipv4" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  description       = "HTTP redirect only"
}
resource "aws_vpc_security_group_ingress_rule" "alb_https_ipv4" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "Public HTTPS"
}
resource "aws_vpc_security_group_egress_rule" "alb_web" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.web.id
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
}
resource "aws_vpc_security_group_egress_rule" "alb_api" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.api.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "web" {
  name        = "${local.name}-web"
  description = "Hosted Next.js tasks"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.common_tags, { component = "web" })
}
resource "aws_security_group" "api" {
  name        = "${local.name}-api"
  description = "Hosted FastAPI tasks"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.common_tags, { component = "api" })
}
resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "Hosted worker and dispatcher tasks"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.common_tags, { component = "worker" })
}
resource "aws_vpc_security_group_ingress_rule" "web_from_alb" {
  security_group_id            = aws_security_group.web.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
}
resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}
resource "aws_vpc_security_group_egress_rule" "task_https" {
  for_each          = { web = aws_security_group.web.id, api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id = each.value
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "Controlled internet/AWS API egress through NAT or endpoints"
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "RDS PostgreSQL from application tasks only"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.common_tags, { component = "database" })
}
resource "aws_vpc_security_group_ingress_rule" "database_from_tasks" {
  for_each                     = { web = aws_security_group.web.id, api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = each.value
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
resource "aws_vpc_security_group_egress_rule" "task_database" {
  for_each                     = { web = aws_security_group.web.id, api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id            = each.value
  referenced_security_group_id = aws_security_group.database.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "endpoints" {
  name        = "${local.name}-endpoints"
  description = "Private AWS service endpoints"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.common_tags, { component = "network" })
}
resource "aws_vpc_security_group_ingress_rule" "endpoints_https" {
  for_each                     = { web = aws_security_group.web.id, api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = each.value
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

