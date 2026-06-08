# CONTEXT — nyc-taxi-case

> Vocabulário e contexto load-bearing do projeto. Skills consultam este arquivo.

## O que é

Pipeline de ingestão da TLC NYC Yellow Taxi (Jan–Maio 2023) implementado
com Databricks Asset Bundle + Lakeflow Declarative Pipelines (DLT) +
Auto Loader, rodando em **Databricks Free Edition**.

## Vocabulário load-bearing

- **TLC** — NY Taxi & Limousine Commission (fonte dos parquets)
- **Yellow taxi** — categoria foco do case (não green, fhv, fhvhv)
- **Landing** — Volume Unity Catalog onde o parquet bruto aterra antes do DLT
- **Pipeline DLT** — Lakeflow SDP com bronze + silver + gold
- **Bronze** — streaming table via Auto Loader, raw + metadata
- **Silver** — materialized view, fiel à fonte, snake_case, tipada,
  7 expectations DLT, particionada por `pickup_year_month`
- **Gold** — view SQL com as 5 colunas exigidas pelo case + derivadas
- **pickup_year_month** — STRING `YYYY-MM` derivada de `tpep_pickup_datetime`
  (NÃO do nome do arquivo — fonte tem ruído de pickup em 2001/2087)
- **Janela** — par `--start_year_month` + `--end_year_month`, inclusivo
- **Free Edition** — Databricks gratuito, serverless-only, sem SP, outbound restrita
- **Audit table** — `${prefix}monitoring.landing_audit`, cobre gap pre-Bronze
- **Trio de consumo** — `.sql` puros + notebook `answers.py` + AI/BI dashboard

## NÃO-objetivos (explícitos)

- NÃO ingerir green/fhv/fhvhv (escopo case = yellow only)
- NÃO fazer deploy via CI (Free Edition não suporta service principal)
- NÃO usar Genie / DuckDB como camada de consumo (decisão consciente)

## Decisões load-bearing

Ver `docs/PLAN.md` seção 3 e `docs/adr/` (gerados ao longo da execução).
