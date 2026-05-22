import os

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from app.rag.reranker.base import BaseReranker, RerankerConfig
from app.utils.logger import get_logger

_logger = get_logger("RAG.CausalLMReranker")

DEFAULT_INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"


class CausalLMReranker(BaseReranker):
    """基于因果语言模型的重排序器。

    使用因果语言模型计算正样本和负样本 token 的 logit 差异来评估相关性。
    """

    async def _load_model(self):
        """加载因果语言模型和分词器（懒加载）。

        Returns:
            模型和分词器元组。
        """
        if self._model is None:
            actual_path = self._resolve_model_path()
            _logger.info("【_load_model】加载模型: %s", actual_path)

            self._tokenizer = AutoTokenizer.from_pretrained(actual_path, padding_side="left")
            self._model = AutoModelForCausalLM.from_pretrained(
                actual_path,
                torch_dtype=torch.float16 if self.config.device == "cuda" else torch.float32,
                device_map="auto" if self.config.device == "cuda" else None,
            )
            self._model.eval()

            self._positive_id = self._tokenizer.convert_tokens_to_ids(self.config.positive_token)
            self._negative_id = self._tokenizer.convert_tokens_to_ids(self.config.negative_token)

            if self._positive_id is None or self._negative_id is None:
                _logger.error(
                    "【_load_model】分词器缺少必需的 token: positive=%s, negative=%s",
                    self.config.positive_token,
                    self.config.negative_token,
                )
                raise ValueError(
                    f"Tokenizer does not have '{self.config.positive_token}' or '{self.config.negative_token}' tokens"
                )

            _logger.info(
                "【_load_model】模型加载成功, device: %s, positive_id: %d, negative_id: %d",
                self.config.device,
                self._positive_id,
                self._negative_id,
            )

        return self._model, self._tokenizer

    def _resolve_model_path(self) -> str:
        """解析模型路径，查找包含 config.json 的目录。

        Returns:
            模型目录路径。
        """
        path = self.config.local_path
        if os.path.exists(os.path.join(path, "config.json")):
            return path

        for root, dirs, files in os.walk(path):
            if "config.json" in files:
                _logger.info("【_resolve_model_path】找到模型路径: %s", root)
                return root

        _logger.debug("【_resolve_model_path】使用默认路径: %s", path)
        return path

    async def _format_pairs(self, query: str, documents: list[str]) -> list[str]:
        """格式化查询-文档对为模型输入格式。

        Args:
            query: 查询语句。
            documents: 文档列表。

        Returns:
            格式化后的输入字符串列表。
        """
        model, tokenizer = await self._load_model()
        instruction = self.config.instruction or DEFAULT_INSTRUCTION

        prefix = self.config.prefix_template
        suffix = self.config.suffix_template

        prefix_tokens = tokenizer.encode(prefix, add_special_tokens=False)
        suffix_tokens = tokenizer.encode(suffix, add_special_tokens=False)

        max_len = self.config.max_length - len(prefix_tokens) - len(suffix_tokens)

        formatted_pairs = []
        for doc in documents:
            output = self.config.input_template.format(instruction=instruction, query=query, document=doc)
            inputs = tokenizer(
                output,
                padding=False,
                truncation="longest_first",
                return_attention_mask=False,
                max_length=max_len,
            )
            input_ids = prefix_tokens + inputs["input_ids"] + suffix_tokens
            formatted_pairs.append(tokenizer.decode(input_ids, skip_special_tokens=True))

        _logger.debug("【_format_pairs】格式化完成，生成 %d 个配对", len(formatted_pairs))
        return formatted_pairs

    async def _compute_scores(self, pairs: list[str]) -> list[float]:
        """使用因果语言模型计算相关性分数。

        Args:
            pairs: 格式化后的输入字符串列表。

        Returns:
            相关性分数列表。
        """
        model, tokenizer = await self._load_model()

        inputs = tokenizer(
            pairs,
            padding=True,
            return_tensors="pt",
            truncation=True,
            max_length=self.config.max_length,
        )

        for key in inputs:
            if isinstance(inputs[key], torch.Tensor):
                inputs[key] = inputs[key].to(model.device)

        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits[:, -1, :]

        positive_logits = logits[:, self._positive_id]
        negative_logits = logits[:, self._negative_id]

        scores = torch.stack([negative_logits, positive_logits], dim=1)
        scores = torch.nn.functional.log_softmax(scores, dim=1)
        scores = scores[:, 1].exp().tolist()

        _logger.debug("【_compute_scores】计算完成，返回 %d 个分数", len(scores))
        return scores
