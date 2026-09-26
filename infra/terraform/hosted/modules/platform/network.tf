resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = local.name, component = "network" })
}
resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.common_tags, { Name = local.name, component = "network" })
}
resource "aws_subnet" "public" {
  for_each                = local.azs
  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, each.value)
  map_public_ip_on_launch = false
  tags                    = merge(local.common_tags, { Name = "${local.name}-public-${each.value + 1}", component = "network", tier = "public" })
}
resource "aws_subnet" "application" {
  for_each                = local.azs
  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, each.value + 4)
  map_public_ip_on_launch = false
  tags                    = merge(local.common_tags, { Name = "${local.name}-app-${each.value + 1}", component = "network", tier = "private-application" })
}
resource "aws_subnet" "database" {
  for_each                = local.azs
  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, each.value + 8)
  map_public_ip_on_launch = false
  tags                    = merge(local.common_tags, { Name = "${local.name}-db-${each.value + 1}", component = "network", tier = "isolated-database" })
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = merge(local.common_tags, { Name = "${local.name}-public", component = "network" })
}
resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}
resource "aws_eip" "nat" {
  for_each   = local.nat_azs
  domain     = "vpc"
  tags       = merge(local.common_tags, { Name = "${local.name}-nat-${each.value + 1}", component = "network" })
  depends_on = [aws_internet_gateway.this]
}
resource "aws_nat_gateway" "this" {
  for_each      = local.nat_azs
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id
  tags          = merge(local.common_tags, { Name = "${local.name}-nat-${each.value + 1}", component = "network" })
}
resource "aws_route_table" "application" {
  for_each = local.azs
  vpc_id   = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[var.nat_gateway_mode == "per_az" ? each.key : var.availability_zones[0]].id
  }
  tags = merge(local.common_tags, { Name = "${local.name}-app-${each.value + 1}", component = "network" })
}
resource "aws_route_table_association" "application" {
  for_each       = aws_subnet.application
  subnet_id      = each.value.id
  route_table_id = aws_route_table.application[each.key].id
}
resource "aws_route_table" "database" {
  for_each = local.azs
  vpc_id   = aws_vpc.this.id
  tags     = merge(local.common_tags, { Name = "${local.name}-db-${each.value + 1}", component = "network" })
}
resource "aws_route_table_association" "database" {
  for_each       = aws_subnet.database
  subnet_id      = each.value.id
  route_table_id = aws_route_table.database[each.key].id
}
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for table in aws_route_table.application : table.id]
  tags              = merge(local.common_tags, { Name = "${local.name}-s3", component = "network" })
}
resource "aws_vpc_endpoint" "interface" {
  for_each            = var.enable_interface_endpoints ? local.endpoint_services : toset([])
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for subnet in aws_subnet.application : subnet.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  tags                = merge(local.common_tags, { Name = "${local.name}-${replace(each.value, ".", "-")}", component = "network" })
}
