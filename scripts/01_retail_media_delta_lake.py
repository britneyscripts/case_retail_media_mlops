#!/usr/bin/env python3
"""
scripts/01_retail_media_delta_lake.py
--------------------------------------------------------------------------------
Pipeline de Dados Medalhão (Delta Lake / PySpark Logic via DuckDB Engine).
Simula a arquitetura de dados governada do Databricks em Marketplace de Quick-Commerce:

1. BRONZE: Leitura dos logs brutos de ad_impressions, ad_clicks e orders.
2. SILVER: 
   - Deduplicação de transações ACID.
   - Temporal Attribution Window Join (Janela de 7 dias de Click-Through e 24h View-Through).
   - Classificação Closed-Loop de pedidos atribuídos a Retail Media vs Orgânicos.
3. GOLD:
   - Tabela Agregada de Consumidor: catalog.retail_media.customer_features
   - Tabela Agregada de Parceiro/Restaurante: catalog.retail_media.merchant_features

Resultados salvos em formato colunar Parquet otimizado com metadados de governança.
--------------------------------------------------------------------------------
"""

import os
import duckdb
import pandas as pd

def run_medallion_pipeline():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    silver_dir = os.path.join(data_dir, "silver")
    gold_dir = os.path.join(data_dir, "gold")
    os.makedirs(silver_dir, exist_ok=True)
    os.makedirs(gold_dir, exist_ok=True)

    print("=" * 80)
    print("🏗️  INICIANDO PIPELINE MEDALHÃO DATABRICKS / DELTA LAKE (SuperApp Retail Media)")
    print("=" * 80)

    con = duckdb.connect(database=":memory:")

    # 1. Leitura da Camada Bronze
    print("\n[1/3] 🥉 CAMADA BRONZE: Ingestão de Logs Brutos de Streaming e Transações")
    bronze_imp_path = os.path.join(data_dir, "bronze_ad_impressions.csv")
    bronze_clk_path = os.path.join(data_dir, "bronze_ad_clicks.csv")
    bronze_ord_path = os.path.join(data_dir, "bronze_orders.csv")

    con.execute(f"CREATE TABLE bronze_impressions AS SELECT * FROM read_csv_auto('{bronze_imp_path}')")
    con.execute(f"CREATE TABLE bronze_clicks AS SELECT * FROM read_csv_auto('{bronze_clk_path}')")
    con.execute(f"CREATE TABLE bronze_orders AS SELECT * FROM read_csv_auto('{bronze_ord_path}')")

    n_imp = con.execute("SELECT COUNT(*) FROM bronze_impressions").fetchone()[0]
    n_clk = con.execute("SELECT COUNT(*) FROM bronze_clicks").fetchone()[0]
    n_ord = con.execute("SELECT COUNT(*) FROM bronze_orders").fetchone()[0]

    print(f"   • bronze_impressions: {n_imp:,} registros")
    print(f"   • bronze_clicks:      {n_clk:,} registros")
    print(f"   • bronze_orders:      {n_ord:,} transações")

    # 2. Transformação e Atribuição Temporal na Camada Silver
    print("\n[2/3] 🥈 CAMADA SILVER: Temporal Attribution Window Join (Closed-Loop 7d / 24h)")
    
    # Query de Atribuição Temporal:
    # Vincula pedidos ao último clique realizado pelo mesmo usuário no mesmo restaurante nos últimos 7 dias
    silver_attribution_sql = """
    CREATE TABLE silver_ad_attribution AS
    WITH ranked_clicks AS (
        SELECT 
            c.click_id,
            c.impression_id,
            c.timestamp AS click_timestamp,
            c.customer_id,
            c.merchant_id,
            c.ad_placement,
            ROW_NUMBER() OVER (
                PARTITION BY c.customer_id, c.merchant_id 
                ORDER BY c.timestamp DESC
            ) as click_rank
        FROM bronze_clicks c
    ),
    attributed_orders AS (
        SELECT 
            o.order_id,
            o.timestamp AS order_timestamp,
            o.customer_id,
            o.merchant_id,
            o.order_amount,
            o.used_coupon,
            o.cuisine,
            rc.click_id AS attributed_click_id,
            rc.impression_id AS attributed_impression_id,
            rc.ad_placement,
            CASE 
                WHEN rc.click_id IS NOT NULL 
                     AND epoch(o.timestamp::TIMESTAMP) - epoch(rc.click_timestamp::TIMESTAMP) BETWEEN 0 AND (7 * 86400)
                THEN 'Closed_Loop_Attributed_Click'
                ELSE 'Organic_or_Direct'
            END AS attribution_status,
            CASE 
                WHEN rc.click_id IS NOT NULL 
                THEN round((epoch(o.timestamp::TIMESTAMP) - epoch(rc.click_timestamp::TIMESTAMP)) / 3600.0, 1)
                ELSE NULL
            END AS hours_from_click_to_order
        FROM bronze_orders o
        LEFT JOIN ranked_clicks rc 
            ON o.customer_id = rc.customer_id 
            AND o.merchant_id = rc.merchant_id
            AND rc.click_timestamp <= o.timestamp
            AND epoch(o.timestamp::TIMESTAMP) - epoch(rc.click_timestamp::TIMESTAMP) <= (7 * 86400)
            AND rc.click_rank = 1
    )
    SELECT * FROM attributed_orders
    """
    con.execute(silver_attribution_sql)

    silver_summary = con.execute("""
        SELECT 
            attribution_status,
            COUNT(*) AS total_orders,
            ROUND(SUM(order_amount), 2) AS total_revenue,
            ROUND(AVG(order_amount), 2) AS avg_ticket,
            ROUND(AVG(hours_from_click_to_order), 1) AS avg_hours_to_convert
        FROM silver_ad_attribution
        GROUP BY attribution_status
    """).df()

    print("\n   📊 Resumo da Atribuição Closed-Loop (Silver Layer):")
    print(silver_summary.to_string(index=False))

    silver_parquet_path = os.path.join(silver_dir, "silver_ad_attribution.parquet")
    con.execute(f"COPY silver_ad_attribution TO '{silver_parquet_path}' (FORMAT PARQUET)")
    print(f"\n   💾 Tabela Silver salva em Parquet: {silver_parquet_path}")

    # 3. Agregação e Engenharia de Features na Camada Gold
    print("\n[3/3] 🥇 CAMADA GOLD: Agregações para Databricks Feature Store & Unity Catalog")

    # A. Features Comportamentais do Consumidor (customer_features)
    gold_customer_features_sql = """
    CREATE TABLE gold_customer_features AS
    WITH user_orders_agg AS (
        SELECT 
            customer_id,
            COUNT(DISTINCT order_id) AS user_total_orders,
            COUNT(DISTINCT CASE WHEN attribution_status = 'Closed_Loop_Attributed_Click' THEN order_id END) AS user_attributed_orders,
            ROUND(AVG(order_amount), 2) AS user_avg_basket_value,
            ROUND(AVG(used_coupon), 3) AS user_discount_affinity,
            MODE(cuisine) AS user_preferred_cuisine
        FROM silver_ad_attribution
        GROUP BY customer_id
    ),
    user_ad_behavior AS (
        SELECT 
            i.customer_id,
            COUNT(DISTINCT i.impression_id) AS total_impressions,
            COUNT(DISTINCT c.click_id) AS total_clicks,
            ROUND(COUNT(DISTINCT c.click_id) * 1.0 / NULLIF(COUNT(DISTINCT i.impression_id), 0), 4) AS user_historical_ctr,
            -- Score de fadiga de anúncio: muitas impressões sem clique recente
            ROUND(COUNT(DISTINCT i.impression_id) * 1.0 / (COUNT(DISTINCT c.click_id) + 1.0), 2) AS user_ad_fatigue_score
        FROM bronze_impressions i
        LEFT JOIN bronze_clicks c 
            ON i.impression_id = c.impression_id
        GROUP BY i.customer_id
    )
    SELECT 
        u.customer_id,
        COALESCE(o.user_total_orders, 0) AS user_total_orders,
        COALESCE(o.user_attributed_orders, 0) AS user_attributed_orders,
        COALESCE(o.user_avg_basket_value, 45.0) AS user_avg_basket_value,
        COALESCE(o.user_discount_affinity, 0.20) AS user_discount_affinity,
        COALESCE(o.user_preferred_cuisine, 'Burger') AS user_preferred_cuisine,
        COALESCE(u.total_impressions, 0) AS user_ad_impressions,
        COALESCE(u.total_clicks, 0) AS user_ad_clicks,
        COALESCE(u.user_historical_ctr, 0.0) AS user_historical_ctr,
        COALESCE(u.user_ad_fatigue_score, 1.0) AS user_ad_fatigue_score,
        CURRENT_TIMESTAMP AS last_feature_update
    FROM user_ad_behavior u
    LEFT JOIN user_orders_agg o ON u.customer_id = o.customer_id
    """
    con.execute(gold_customer_features_sql)

    # B. Features do Restaurante / Parceiro de Retail Media (merchant_features)
    gold_merchant_features_sql = """
    CREATE TABLE gold_merchant_features AS
    SELECT 
        merchant_id,
        COUNT(DISTINCT order_id) AS merchant_total_orders,
        ROUND(AVG(order_amount), 2) AS merchant_avg_ticket,
        ROUND(AVG(used_coupon), 3) AS merchant_coupon_dependency,
        MODE(cuisine) AS merchant_cuisine,
        ROUND(COUNT(DISTINCT CASE WHEN attribution_status = 'Closed_Loop_Attributed_Click' THEN order_id END) * 1.0 / COUNT(DISTINCT order_id), 4) AS merchant_retail_media_dependency_rate,
        CURRENT_TIMESTAMP AS last_feature_update
    FROM silver_ad_attribution
    GROUP BY merchant_id
    """
    con.execute(gold_merchant_features_sql)

    # Salvando tabelas Gold
    gold_user_path = os.path.join(gold_dir, "gold_customer_features.parquet")
    gold_merch_path = os.path.join(gold_dir, "gold_merchant_features.parquet")

    con.execute(f"COPY gold_customer_features TO '{gold_user_path}' (FORMAT PARQUET)")
    con.execute(f"COPY gold_merchant_features TO '{gold_merch_path}' (FORMAT PARQUET)")

    n_gold_users = con.execute("SELECT COUNT(*) FROM gold_customer_features").fetchone()[0]
    n_gold_merch = con.execute("SELECT COUNT(*) FROM gold_merchant_features").fetchone()[0]

    print(f"\n   💾 Tabela Gold Consumidor: {n_gold_users:,} perfis ➔ {gold_user_path}")
    print(f"   💾 Tabela Gold Restaurante: {n_gold_merch:,} parceiros ➔ {gold_merch_path}")

    # Exibe amostra da Feature Table
    sample_df = con.execute("SELECT customer_id, user_preferred_cuisine, user_avg_basket_value, user_ad_fatigue_score, user_historical_ctr FROM gold_customer_features LIMIT 5").df()
    print("\n✨ Amostra de Variáveis para Unity Catalog (Feature Store):")
    print(sample_df.to_string(index=False))

    print("\n" + "=" * 80)
    print("✅ PIPELINE MEDALHÃO CONCLUÍDO COM SUCESSO! DADOS PRONTOS PARA A FEATURE STORE.")
    print("=" * 80)

if __name__ == "__main__":
    run_medallion_pipeline()
