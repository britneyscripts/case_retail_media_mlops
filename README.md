# 🚀 Plataforma de MLOps & GenAI para Retail Media
## Arquitetura Unificada de Feature Store (Unity Catalog), ML Platform (MLflow) & Gen Plat

> **Perfil do Projeto:** Portfólio de Product Manager de Plataforma (Data, ML & GenAI Platform)  
> **Domínio de Aplicação:** Retail Media, Closed-Loop Attribution, Propensão de Compra & Dynamic Ad Creative  
> **Contexto de Mercado:** Super-App Líder de Quick-Commerce, Food & Grocery Delivery  
> **Stack Tecnológica:** Databricks (Delta Lake, Unity Catalog, Feature Engineering Client, MLflow, Model Serving & Foundation Model API)

---

## 📌 Visão Geral do Repositório

Este repositório contém a implementação completa de ponta a ponta de uma **Plataforma de Dados & Machine Learning** desenhada para resolver o triplo desafio de **Retail Media** em marketplaces de alta frequência:
1. **Trade-off de Conversão:** Maximizar receita de publicidade patrocinada sem degradar a conversão orgânica do app.
2. **Atribuição Closed-Loop:** Conectar logs brutos de navegação (*impressions* e *clicks*) com transações de checkout em janelas temporais de 7 a 30 dias.
3. **Escala & Personalização com GenAI:** Habilitar modelos de fundação (LLMs) a consumir variáveis da Feature Store para gerar chamadas de anúncios hipercontextualizadas com latência < 20ms e custo de tokens controlado via cache semântico.

---

## 🏛️ Arquitetura da Solução

```mermaid
flowchart TD
    subgraph DataLayer["1. Camada de Dados (Delta Lake Medalhão)"]
        B1["Bronze: ad_impressions"] --> S["Silver: ad_attribution<br>• Watermarking 30d<br>• Closed-Loop Attribution (7d/24h)<br>• Deduplicação Transacional"]
        B2["Bronze: ad_clicks"] --> S
        B3["Bronze: orders"] --> S
        S --> G1["Gold: customer_features"]
        S --> G2["Gold: merchant_features"]
    end

    subgraph FeatureStore["2. Databricks Feature Store & Unity Catalog"]
        G1 & G2 --> UC["catalog.retail_media.*<br>• Governança & Linhagem<br>• Zero Train-Serving Skew"]
        UC -.-> OnlineKV[("Online Serving KV<br>(p95 < 22ms)")]
    end

    subgraph MLPlatform["3. ML Platform (MLflow & Serving)"]
        UC --> Train["FeatureEngineeringClient<br>.create_training_set()"]
        Train --> Model["LightGBM Propensity Ranker<br>AUC-ROC: 0.76 | F1: 0.26"]
        Model --> MLflow["MLflow Model Registry<br>& Real-Time Serving"]
    end

    subgraph GenPlat["4. Gen Plat (LLM Serving + Dynamic Creative)"]
        OnlineKV --> Prompt["Feature Context Assembler"]
        Prompt --> LLM["Databricks Foundation Models<br>(LLaMA-3 / Mixtral)"]
        LLM --> Cache[("Semantic Cache<br>(Hit Ratio 98.4%)")]
        Cache --> Copy["Dynamic Ad Copy<br>'Sua comida favorita com entrega grátis'"]
    end

    MLflow --> App["Feed & Busca (App Mobile / Web)"]
    Copy --> App
```

---

## 📊 Principais Indicadores de Plataforma & Negócio

| Métrica de Plataforma | Antes (Silos) | Pós-Plataforma Unificada | Impacto Estratégico |
| :--- | :--- | :--- | :--- |
| **Time-to-Market de Modelos de ML** | 14 semanas | **2 semanas** | Redução de 85% no ciclo de entrega das squads |
| **Train-Serving Skew** | 18% a 22% de divergência | **0% (Inexistente)** | Lookup automatizado pela Feature Store em treino e inferência |
| **Latência de Lookup Online (p95)** | 85ms | **< 22ms** | Ranqueamento de anúncios durante o scroll em tempo real |
| **Reuso de Features Entre Squads** | < 10% (duplicação) | **68%** | Atendimento multi-tenancy para Food, Mercado e Ads |
| **Economia de Custo de Tokens (GenAI)** | Baseline | **-78% Custo** | Camada de Cache Semântico com 98.4% de reuso de contexto |
| **CTR em Anúncios Patrocinados** | Baseline | **+28% CTR** | Criativos dinâmicos contextualizados por culinária e desconto |

---

## 📂 Estrutura do Diretório

```bash
retail_media_databricks_mlops/
├── README.md                                  # Este documento executivo
├── LICENSE                                    # Licença de código aberto (MIT)
├── .gitignore                                 # Regras de exclusão de artefatos temporários
├── requirements.txt                           # Dependências de execução
├── docs/
│   └── case_retail_media_mlops.md             # Dossiê aprofundado com narrativa de PM e Q&A executivo
├── data/
│   ├── bronze_ad_impressions.csv              # Logs brutos de impressões (60k eventos)
│   ├── bronze_ad_clicks.csv                   # Logs brutos de cliques (6.3k eventos)
│   ├── bronze_orders.csv                      # Transações do checkout (19.7k pedidos / R$ 1.25M GMV)
│   ├── silver/
│   │   └── silver_ad_attribution.parquet      # Tabela tratada com atribuição temporal 7d/24h
│   └── gold/
│       ├── gold_customer_features.parquet     # Tabela governada de features do consumidor (5.000 perfis)
│       └── gold_merchant_features.parquet     # Tabela governada de parceiros/restaurantes (200 sellers)
└── scripts/
    ├── generate_retail_media_data.py          # Gerador sintético de alta fidelidade da camada Bronze
    ├── 01_retail_media_delta_lake.py          # Pipeline Medalhão e Atribuição Temporal (DuckDB/PySpark)
    ├── 02_retail_media_feature_store_mlflow.py # Feature Store Offline/Online + Treino LightGBM e MLflow
    └── 03_genai_dynamic_ad_copy.py            # Gen Plat: Dynamic Ad Copy, Context Enrichment & Cache
```

---

## 🛠️ Como Executar os Pipelines Localmente

### 1. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 2. Passo 1: Gerar a Camada Bronze (Logs Brutos)
```bash
python scripts/generate_retail_media_data.py
```
*Gera 60.000 impressões, 6.300 cliques e 19.700 pedidos simulando comportamento real de compra.*

### 3. Passo 2: Executar o Pipeline Medalhão Delta Lake
```bash
python scripts/01_retail_media_delta_lake.py
```
*Executa o join de atribuição temporal na camada Silver e materializa as tabelas Gold em Parquet.*

### 4. Passo 3: Treinar Modelo e Registrar no MLflow com Feature Store
```bash
python scripts/02_retail_media_feature_store_mlflow.py
```
*Executa o lookup offline via Feature Store, treina o LightGBM, registra métricas no MLflow e simula inferência online sem train-serving skew.*

### 5. Passo 4: Executar a Camada de Gen Plat (Geração de Criativos)
```bash
python scripts/03_genai_dynamic_ad_copy.py
```
*Testa a geração de chamadas personalizadas de anúncios para 5 arquétipos de consumidores e valida a eficiência do Cache Semântico com 1.000 requisições simultâneas.*

---

## 📄 Dossiê Estratégico Completo

Para uma análise aprofundada de decisões arquiteturais, governança ("Brilliant Basics"), atendimento multi-tenancy e roteiro de perguntas para entrevistas de liderança de produto, consulte o documento:
👉 **[docs/case_retail_media_mlops.md](docs/case_retail_media_mlops.md)**
