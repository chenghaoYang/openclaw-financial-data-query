"""增强召回模块 - Online模式

提供基于语义向量的智能召回能力，完全替代原有的Grep搜索流程。

核心组件:
- pipeline: 召回Pipeline（Query改写 → 多路召回 → RRF融合 → 重排序）
- providers: 服务提供者（Embedding、Reranker、Retriever）
- utils: 工具模块（Domain Router、Market Rules等）
"""

__version__ = "1.0.0"
