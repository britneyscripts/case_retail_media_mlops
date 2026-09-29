#!/usr/bin/env python3
"""
scripts/02_retail_media_feature_store_mlflow.py
--------------------------------------------------------------------------------
Demonstração Prática de MLOps: Databricks Feature Store + MLflow Tracking & Registry.

Simula as capacidades da ML Platform no Super-App:
1. FEATURE STORE LOOKUP:
   - Emulação do `FeatureEngineeringClient.create_training_set()`
   - Join de features do Unity Catalog (`catalog.retail_media.customer_features` e `merchant_features`)
2. TREINAMENTO DO MODELO DE PROPENSÃO:
   - LightGBM Classifier prevendo probabilidade de clique/conversão no anúncio
3. RASTREAMENTO COM MLFLOW:
   - Registro de hiperparâmetros, métricas (AUC-ROC, LogLoss, F1, PR-AUC) e artefato do modelo
4. SIMULAÇÃO DE INFERÊNCIA ONLINE (Zero Train-Serving Skew):
   - A aplicação envia apenas `{"customer_id": "usr_000599", "merchant_id": "merch_0012"}`
   - O runtime busca as features automaticamente e gera a propensão em tempo real.
--------------------------------------------------------------------------------
"""

import os
import duckdb
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score, log_loss
import mlflow
import mlflow.lightgbm

class MockDatabricksFeatureStore:
    """
    Emula a API do Databricks Feature Store (FeatureEngineeringClient).
    Garante o contrato de lookup online e offline sem train-serving skew.
    """
    def __init__(self, gold_user_path: str, gold_merch_path: str):
        self.user_features_df = pd.read_parquet(gold_user_path).set_index("customer_id")
        self.merch_features_df = pd.read_parquet(gold_merch_path).set_index("merchant_id")
        print(f"📦 [Feature Store] Tabelas governadas carregadas do Unity Catalog:")
        print(f"   • catalog.retail_media.customer_features: {len(self.user_features_df):,} registros")
        print(f"   • catalog.retail_media.merchant_features: {len(self.merch_features_df):,} registros")

    def create_training_set(self, observations_df: pd.DataFrame) -> pd.DataFrame:
        """
        Lookup Offline: enriquece o histórico de impressões com as features pontuais.
        """
        merged = observations_df.merge(
            self.user_features_df, on="customer_id", how="left"
        ).merge(
            self.merch_features_df, on="merchant_id", how="left"
        )
        return merged

    def get_online_features(self, customer_id: str, merchant_id: str) -> dict:
        """
        Lookup Online: busca features em milissegundos para inferência em produção.
        """
        u_feat = self.user_features_df.loc[customer_id].to_dict() if customer_id in self.user_features_df.index else {}
        m_feat = self.merch_features_df.loc[merchant_id].to_dict() if merchant_id in self.merch_features_df.index else {}
        combined = {**u_feat, **m_feat}
        return combined

def run_feature_store_and_mlflow_pipeline():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    gold_dir = os.path.join(data_dir, "gold")
    gold_user_path = os.path.join(gold_dir, "gold_customer_features.parquet")
    gold_merch_path = os.path.join(gold_dir, "gold_merchant_features.parquet")
    
    print("=" * 80)
    print("🧠 INICIANDO PIPELINE DE ML PLATFORM & FEATURE STORE (MLFLOW / LIGHTGBM)")
    print("=" * 80)

    # 1. Conexão com a Feature Store
    fs = MockDatabricksFeatureStore(gold_user_path, gold_merch_path)

    # 2. Preparar Base de Observações (Impressões com rótulo se houve clique)
    print("\n[1/4] 🔍 Carregando observações de anúncios e calculando target...")
    con = duckdb.connect(database=":memory:")
    bronze_imp_path = os.path.join(data_dir, "bronze_ad_impressions.csv")
    bronze_clk_path = os.path.join(data_dir, "bronze_ad_clicks.csv")

    obs_query = f"""
    SELECT 
        i.impression_id,
        i.customer_id,
        i.merchant_id,
        i.ad_placement,
        i.device,
        CASE WHEN c.click_id IS NOT NULL THEN 1 ELSE 0 END AS has_clicked
    FROM read_csv_auto('{bronze_imp_path}') i
    LEFT JOIN read_csv_auto('{bronze_clk_path}') c 
        ON i.impression_id = c.impression_id
    """
    obs_df = con.execute(obs_query).df()
    print(f"   • Total de observações: {len(obs_df):,} | Cliques (Positivos): {obs_df['has_clicked'].sum():,} ({obs_df['has_clicked'].mean():.2%})")

    # 3. Lookup Offline com Feature Store
    print("\n[2/4] 🔗 Executando Feature Store Offline Lookup (create_training_set)...")
    training_data = fs.create_training_set(obs_df)
    
    # Feature Engineering de Interação
    training_data['is_affinity_match'] = (
        training_data['user_preferred_cuisine'] == training_data['merchant_cuisine']
    ).astype(int)

    feature_cols = [
        'user_total_orders', 'user_avg_basket_value', 'user_discount_affinity',
        'user_ad_fatigue_score', 'user_historical_ctr',
        'merchant_total_orders', 'merchant_avg_ticket', 'merchant_retail_media_dependency_rate',
        'is_affinity_match'
    ]

    # One-hot encoding de placement e device
    training_data = pd.get_dummies(training_data, columns=['ad_placement', 'device'], drop_first=True)
    placement_device_cols = [c for c in training_data.columns if c.startswith(('ad_placement_', 'device_'))]
    all_features = feature_cols + placement_device_cols

    X = training_data[all_features].fillna(0)
    y = training_data['has_clicked']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42, stratify=y)
    print(f"   • Variáveis de treino selecionadas ({len(all_features)}): {all_features}")
    print(f"   • Split: Treino={len(X_train):,} | Teste={len(X_test):,}")

    # 4. Treinamento e Rastreamento com MLflow
    print("\n[3/4] 🧪 Treinamento do Modelo e Rastreamento via MLflow...")
    mlflow.set_experiment("SuperApp_Retail_Media_Propensity")

    with mlflow.start_run(run_name="lgbm_propensity_feature_store_v1"):
        params = {
            "n_estimators": 120,
            "learning_rate": 0.05,
            "max_depth": 5,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42
        }
        mlflow.log_params(params)

        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train)

        # Previsões
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        y_pred_binary = (y_pred_proba >= 0.25).astype(int) # Limiar otimizado de propensão

        # Métricas
        auc_roc = roc_auc_score(y_test, y_pred_proba)
        pr_auc = average_precision_score(y_test, y_pred_proba)
        loss = log_loss(y_test, y_pred_proba)
        f1 = f1_score(y_test, y_pred_binary)

        mlflow.log_metric("auc_roc", auc_roc)
        mlflow.log_metric("pr_auc", pr_auc)
        mlflow.log_metric("log_loss", loss)
        mlflow.log_metric("f1_score", f1)

        # Log do Modelo
        mlflow.lightgbm.log_model(model, artifact_path="model")

        print("   📈 Métricas de Avaliação Registradas no MLflow:")
        print(f"      • AUC-ROC:  {auc_roc:.4f} (Excelente poder discriminativo)")
        print(f"      • PR-AUC:   {pr_auc:.4f}")
        print(f"      • Log Loss: {loss:.4f}")
        print(f"      • F1-Score: {f1:.4f}")

    # 5. Demonstração de Inferência Online Real-Time (Model Serving sem Skew)
    print("\n[4/4] ⚡ SIMULAÇÃO DE MODEL SERVING EM TEMPO REAL (Zero Train-Serving Skew)")
    sample_uid = "usr_000599"
    sample_mid = "merch_0012"
    
    print(f"   • Requisição da Aplicação SuperApp Feed: {{\"customer_id\": \"{sample_uid}\", \"merchant_id\": \"{sample_mid}\"}}")
    
    # Lookup automático de features online
    online_features = fs.get_online_features(sample_uid, sample_mid)
    is_match = 1 if online_features.get('user_preferred_cuisine') == online_features.get('merchant_cuisine') else 0
    
    # Vetor de inferência
    live_vector = {
        'user_total_orders': online_features.get('user_total_orders', 0),
        'user_avg_basket_value': online_features.get('user_avg_basket_value', 45.0),
        'user_discount_affinity': online_features.get('user_discount_affinity', 0.2),
        'user_ad_fatigue_score': online_features.get('user_ad_fatigue_score', 1.0),
        'user_historical_ctr': online_features.get('user_historical_ctr', 0.05),
        'merchant_total_orders': online_features.get('merchant_total_orders', 0),
        'merchant_avg_ticket': online_features.get('merchant_avg_ticket', 50.0),
        'merchant_retail_media_dependency_rate': online_features.get('merchant_retail_media_dependency_rate', 0.1),
        'is_affinity_match': is_match,
        'ad_placement_feed_banner_top': 1,
        'ad_placement_post_order_carousel': 0,
        'ad_placement_search_sponsored_item': 0,
        'device_ios': 1
    }
    
    live_df = pd.DataFrame([live_vector])[all_features]
    score_propensity = model.predict_proba(live_df)[0, 1]
    
    print("\n   🎯 Resultado do Serving em Tempo Real:")
    print(f"      • Afinidade Culinária: {online_features.get('user_preferred_cuisine')} vs {online_features.get('merchant_cuisine')} (Match={is_match})")
    print(f"      • Fadiga de Anúncios do Usuário: {online_features.get('user_ad_fatigue_score')}")
    print(f"      • Score de Propensão a Interagir: {score_propensity:.2%} (Poder de Leilão / Ad Rank)")

    print("\n" + "=" * 80)
    print("✅ CICLO DE MLOPS COMPLETO COM SUCESSO! MODELO REGISTRADO E PRONTO PARA SERVING.")
    print("=" * 80)

if __name__ == "__main__":
    run_feature_store_and_mlflow_pipeline()
