#!/usr/bin/env python3
"""
scripts/generate_retail_media_data.py
--------------------------------------------------------------------------------
Gerador de Dados Sintéticos de Alta Fidelidade para Retail Media em Marketplace de Quick-Commerce.
Simula os 3 fluxos de eventos da camada Bronze:
1. data/bronze_ad_impressions.csv (logs de impressões de anúncios patrocinados)
2. data/bronze_ad_clicks.csv (logs de cliques nos anúncios)
3. data/bronze_orders.csv (transações concluídas no checkout)

Objetivo: Alimentar o pipeline de atribuição Closed-Loop e a Feature Store.
--------------------------------------------------------------------------------
"""

import os
import random
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

def generate_retail_media_datasets(
    n_users: int = 5000,
    n_merchants: int = 200,
    n_impressions: int = 60000,
    days_history: int = 45,
    seed: int = 42
):
    np.random.seed(seed)
    random.seed(seed)
    
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"🚀 Iniciando geração de dados sintéticos de Retail Media (Quick-Commerce Super-App)...")
    print(f"   • Usuários: {n_users:,} | Restaurantes/Parceiros: {n_merchants:,}")
    print(f"   • Volume de Impressões Alvo: {n_impressions:,} | Histórico: {days_history} dias")

    start_date = datetime(2026, 8, 1, 0, 0, 0)
    
    # 1. Criação dos Perfis de Usuários (Consumidores)
    cuisines = ['Pizza', 'Burger', 'Japonesa', 'Brasileira', 'Saudavel', 'Mercado', 'Doces']
    user_ids = [f"usr_{i:06d}" for i in range(1, n_users + 1)]
    
    user_profiles = {}
    for uid in user_ids:
        fav_cuisine = np.random.choice(cuisines, p=[0.24, 0.20, 0.18, 0.15, 0.08, 0.10, 0.05])
        ticket_mean = np.random.choice([35.0, 55.0, 85.0, 140.0], p=[0.30, 0.40, 0.20, 0.10])
        coupon_sensitivity = np.random.beta(a=2, b=3) # Distribuição contínua de propensão a cupom
        order_frequency_weekly = np.random.poisson(lam=1.8) + 0.3
        
        user_profiles[uid] = {
            "preferred_cuisine": fav_cuisine,
            "ticket_mean": ticket_mean,
            "coupon_sensitivity": coupon_sensitivity,
            "freq": order_frequency_weekly
        }

    # 2. Criação dos Restaurantes / Marcas de Retail Media
    merchant_ids = [f"merch_{i:04d}" for i in range(1, n_merchants + 1)]
    merchant_profiles = {}
    for mid in merchant_ids:
        m_cuisine = np.random.choice(cuisines)
        m_rating = round(np.random.uniform(4.0, 5.0), 1)
        m_delivery_time = int(np.random.normal(loc=35, scale=8))
        m_delivery_time = max(18, min(65, m_delivery_time))
        is_retail_media_sponsor = np.random.choice([1, 0], p=[0.45, 0.55])
        
        merchant_profiles[mid] = {
            "cuisine": m_cuisine,
            "rating": m_rating,
            "delivery_time": m_delivery_time,
            "is_sponsor": is_retail_media_sponsor
        }

    sponsor_merchants = [m for m, p in merchant_profiles.items() if p["is_sponsor"] == 1]

    # 3. Geração de Logs de Impressões (Ad Impressions)
    ad_placements = ['feed_banner_top', 'search_sponsored_item', 'post_order_carousel', 'category_highlight']
    devices = ['android', 'ios']
    
    impressions = []
    clicks = []
    orders = []
    
    order_id_seq = 1
    click_id_seq = 1
    
    print("   • Simulando logs de impressões e interações de cliques...")
    for imp_id in range(1, n_impressions + 1):
        uid = random.choice(user_ids)
        user = user_profiles[uid]
        
        # 60% de chance de exibir anúncio da culinária preferida do usuário (personalização algorítmica)
        if random.random() < 0.60:
            eligible_merchants = [m for m in sponsor_merchants if merchant_profiles[m]["cuisine"] == user["preferred_cuisine"]]
            if not eligible_merchants:
                eligible_merchants = sponsor_merchants
        else:
            eligible_merchants = sponsor_merchants
            
        mid = random.choice(eligible_merchants)
        merchant = merchant_profiles[mid]
        
        # Data aleatória no período
        random_seconds = random.randint(0, days_history * 86400)
        imp_time = start_date + timedelta(seconds=random_seconds)
        placement = np.random.choice(ad_placements, p=[0.35, 0.40, 0.15, 0.10])
        device = np.random.choice(devices, p=[0.62, 0.38])
        
        imp_record = {
            "impression_id": f"imp_{imp_id:08d}",
            "timestamp": imp_time.strftime("%Y-%m-%d %H:%M:%S"),
            "customer_id": uid,
            "merchant_id": mid,
            "ad_placement": placement,
            "advertiser_cuisine": merchant["cuisine"],
            "device": device
        }
        impressions.append(imp_record)
        
        # Simulação de Probabilidade de Clique (CTR)
        # Base CTR: ~4.5%
        prob_click = 0.045
        if merchant["cuisine"] == user["preferred_cuisine"]:
            prob_click += 0.065 # Aumento significativo por relevância
        if placement == 'search_sponsored_item':
            prob_click += 0.030 # Busca tem intenção de compra maior
        if merchant["rating"] >= 4.7:
            prob_click += 0.015
            
        if random.random() < prob_click:
            click_delay_sec = random.randint(2, 45)
            click_time = imp_time + timedelta(seconds=click_delay_sec)
            click_record = {
                "click_id": f"clk_{click_id_seq:07d}",
                "impression_id": imp_record["impression_id"],
                "timestamp": click_time.strftime("%Y-%m-%d %H:%M:%S"),
                "customer_id": uid,
                "merchant_id": mid,
                "ad_placement": placement
            }
            clicks.append(click_record)
            click_id_seq += 1
            
            # Conversão Closed-Loop pós-clique (35% de quem clica compra nos próximos 7 dias)
            if random.random() < 0.35:
                order_delay_minutes = random.randint(5, 7 * 24 * 60)
                order_time = click_time + timedelta(minutes=order_delay_minutes)
                
                # Ticket com variação normal
                amount = max(22.0, np.random.normal(loc=user["ticket_mean"], scale=15.0))
                used_coupon = 1 if (random.random() < user["coupon_sensitivity"]) else 0
                
                orders.append({
                    "order_id": f"ord_{order_id_seq:07d}",
                    "timestamp": order_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "customer_id": uid,
                    "merchant_id": mid,
                    "order_amount": round(amount, 2),
                    "used_coupon": used_coupon,
                    "cuisine": merchant["cuisine"],
                    "attribution_source": "ad_click",
                    "origin_click_id": click_record["click_id"]
                })
                order_id_seq += 1

    # 4. Geração de Pedidos Orgânicos (sem interação direta com anúncios)
    print("   • Simulando pedidos orgânicos no app para fechar o ecossistema...")
    n_organic_orders = int(n_users * 3.5)
    for _ in range(n_organic_orders):
        uid = random.choice(user_ids)
        user = user_profiles[uid]
        mid = random.choice(merchant_ids)
        merchant = merchant_profiles[mid]
        
        random_seconds = random.randint(0, days_history * 86400)
        order_time = start_date + timedelta(seconds=random_seconds)
        
        amount = max(20.0, np.random.normal(loc=user["ticket_mean"], scale=12.0))
        used_coupon = 1 if (random.random() < (user["coupon_sensitivity"] * 0.7)) else 0
        
        orders.append({
            "order_id": f"ord_{order_id_seq:07d}",
            "timestamp": order_time.strftime("%Y-%m-%d %H:%M:%S"),
            "customer_id": uid,
            "merchant_id": mid,
            "order_amount": round(amount, 2),
            "used_coupon": used_coupon,
            "cuisine": merchant["cuisine"],
            "attribution_source": "organic",
            "origin_click_id": None
        })
        order_id_seq += 1

    # Conversão para DataFrames
    df_impressions = pd.DataFrame(impressions)
    df_clicks = pd.DataFrame(clicks)
    df_orders = pd.DataFrame(orders)
    
    # Ordenar por timestamp
    df_impressions.sort_values(by="timestamp", inplace=True)
    df_clicks.sort_values(by="timestamp", inplace=True)
    df_orders.sort_values(by="timestamp", inplace=True)
    
    # Salvando os arquivos CSV na camada data/
    path_imp = os.path.join(output_dir, "bronze_ad_impressions.csv")
    path_clk = os.path.join(output_dir, "bronze_ad_clicks.csv")
    path_ord = os.path.join(output_dir, "bronze_orders.csv")
    
    df_impressions.to_csv(path_imp, index=False)
    df_clicks.to_csv(path_clk, index=False)
    df_orders.to_csv(path_ord, index=False)
    
    print(f"\n✅ Dados sintéticos gerados e salvos com sucesso!")
    print(f"   📄 Impressões: {len(df_impressions):,} registros ➔ {path_imp}")
    print(f"   📄 Cliques:    {len(df_clicks):,} registros (CTR médio: {len(df_clicks)/len(df_impressions):.2%}) ➔ {path_clk}")
    print(f"   📄 Pedidos:    {len(df_orders):,} pedidos (Valor total: R$ {df_orders['order_amount'].sum():,.2f}) ➔ {path_ord}")

if __name__ == "__main__":
    generate_retail_media_datasets()
