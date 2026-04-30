import torch
import numpy as np
import os
import json
from datasets import Dataset, DatasetDict
from financial_evaluation.lm_eval.base import Task, rf
from financial_evaluation.lm_eval.metrics import mean, bleu, chrf, ter
from .zhutils import process_zhtext
from seqeval.metrics import f1_score as entity_score
from sklearn.metrics import f1_score, matthews_corrcoef, mean_squared_error

from metrics.qa import qa_metrics
import evaluate

from openai import OpenAI



_DEFAULT_DATASET_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
)
DATASET_PATH = os.path.abspath(os.getenv("MAPFIN_DATA_PATH", _DEFAULT_DATASET_PATH))


class LocalJsonTask(Task):
    def download(self, data_dir=None, cache_dir=None, download_mode=None):
        dataset_path = self.DATASET_PATH
        if data_dir is not None:
            dataset_path = os.path.join(data_dir, os.path.basename(dataset_path))
        dataset_name = os.path.basename(os.path.normpath(dataset_path))
        split_files = {
            "train": os.path.join(dataset_path, f"{dataset_name}_train.json"),
            "validation": os.path.join(dataset_path, f"{dataset_name}_valid.json"),
            "test": os.path.join(dataset_path, f"{dataset_name}_test.json"),
        }
        splits = {}
        for split, path in split_files.items():
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("data", data.get(split, []))
            splits[split] = Dataset.from_list(data)
        if not splits:
            raise FileNotFoundError(f"No local JSON dataset files found in {dataset_path}")
        self.dataset = DatasetDict(splits)



class Classification(LocalJsonTask):
    CALCULATE_MCC = True
    LOWER_CASE = True
    VERSION = 1
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def construct_requests(self, doc, ctx):
        cont_request = rf.greedy_until(ctx, {"until": None})
        return cont_request

    def doc_to_decontamination_query(self, doc):
        return doc["text"]

    def doc_to_text(self, doc):
 
        return doc["query"]

    def doc_to_target(self, doc):
    
        return doc["answer"]

    def process_results(self, doc, results):
        gold: str = doc["choices"][doc["gold"]]
        if self.LOWER_CASE:
            gold = gold.lower()
        ini_result = results[0].strip()
        if self.LOWER_CASE:
            ini_result = ini_result.lower()

        result = None
        for choice in doc["choices"]:
            if self.LOWER_CASE:
                choice = choice.lower()
            if choice in ini_result:
                result = choice
                break
        if result is None:
            result = "missing"

        acc = 1.0 if gold == result else 0.0

        results = {
            "acc": acc,
            "missing": int(result == "missing"),
            "f1": (result, gold),
            "macro_f1": (result, gold),
        }

        if self.CALCULATE_MCC:
            results["mcc"] = (result, gold)

        return results

    def higher_is_better(self):
        metrics = {
            "acc": True,
            "f1": True,
            "macro_f1": True,
            "missing": False,
        }
        if self.CALCULATE_MCC:
            metrics["mcc"] = True
        return metrics

    def weighted_f1(self, items):
        preds, golds = zip(*items)
        labels = list(set(golds))
        preds = np.array(preds)
        golds = np.array(golds)
        f1 = f1_score(golds, preds, average="weighted", labels=labels)
        return f1

    def macro_f1(self, items):
        preds, golds = zip(*items)
        labels = list(set(golds))
        preds = np.array(preds)
        golds = np.array(golds)
        f1 = f1_score(golds, preds, average="macro", labels=labels)
        return f1

    def matthews_corrcoef(self, items):
        preds, golds = zip(*items)
        labels = {label: i for i, label in enumerate(list(set(golds)))}
        preds = [labels.get(pred, -1) for pred in preds]
        golds = [labels.get(gold, -1) for gold in golds]
        return matthews_corrcoef(golds, preds)

    def aggregation(self):
        metrics = {
            "acc": mean,
            "missing": mean,
            "f1": self.weighted_f1,
            "macro_f1": self.macro_f1,
        }
        if self.CALCULATE_MCC:
            metrics["mcc"] = self.matthews_corrcoef
        return metrics

class MapFinAS(Classification):
    DATASET_PATH = os.path.join(DATASET_PATH, "CroFinAS")
class MapFinSA(Classification):
    DATASET_PATH = os.path.join(DATASET_PATH, "CroFinSA")
class MapFinTC(Classification):
    DATASET_PATH = os.path.join(DATASET_PATH, "CroFinTC")

# 文本生成
class Summarization(LocalJsonTask):
    VERSION = 1
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return False

    def has_validation_docs(self):
        return False

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def doc_to_text(self, doc):
        return doc["query"]

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        return {
            "cosine_score": (doc["answer"], results[0]),
        }

    def higher_is_better(self):
        return {
            "cosine_score": True,
        }

    def construct_requests(self, doc, ctx):
        cont_request = rf.greedy_until(ctx, {"until": None})
        return cont_request

    # ===== Batch similarity using GPT embeddings =====
    def cosine_score(self, items):
        """
        items: List[(gold_text, pred_text)]
        """
        
        client = OpenAI(
            base_url=os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )

        MAX_CHARS = 4000  # 避免 embeddings 输入过长报错

        sims = []

        for gold, pred in items:
            gold = "" if gold is None else str(gold)
            pred = "" if pred is None else str(pred)
        
            gold = gold[:MAX_CHARS].strip()
            pred = pred[:MAX_CHARS].strip()
        
            if not gold or not pred:
                sims.append(0.0)
                continue
            
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=[gold, pred]
            )

            gold_vec = np.array(resp.data[0].embedding)
            pred_vec = np.array(resp.data[1].embedding)

            sim = np.dot(gold_vec, pred_vec) / (
                np.linalg.norm(gold_vec) * np.linalg.norm(pred_vec)
            )

            sims.append(sim)

        return float(np.mean(sims))

    def aggregation(self):
        return {
            "cosine_score": self.cosine_score
        }

class MapFinTS(Summarization):
    DATASET_PATH = os.path.join(DATASET_PATH, "CroFinTS")

class QAEval(LocalJsonTask):
    VERSION = 1
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def should_decontaminate(self):
        return True

    def doc_to_decontamination_query(self, doc):
        return doc["text"]

    def doc_to_text(self, doc):
        return doc["query"]

    def construct_requests(self, doc, ctx):
        cont_request = rf.greedy_until(ctx, {"until": None})
        return cont_request

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        pred = results[0].strip()
        gold = doc["answer"].strip()

        return qa_metrics(pred, gold)

    def higher_is_better(self):
        return {
            "acc": True,
            "norm_acc": True,
            "token_f1": True,
            "final_correct": True,
        }

    def aggregation(self):
        return {
            "acc": mean,
            "norm_acc": mean,
            "token_f1": mean,
            "final_correct": mean,
        }

class MapFinQA(QAEval):
    DATASET_PATH = os.path.join(DATASET_PATH, "CroFinQA")

class Matching(LocalJsonTask):
    VERSION = 1
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def should_decontaminate(self):
        return True

    def doc_to_decontamination_query(self, doc):
        return doc["text"]

    def doc_to_text(self, doc):
        return doc["query"]

    def construct_requests(self, doc, ctx):
        cont_request = rf.greedy_until(ctx, {"until": None})
        return cont_request

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        gold = doc["answer"]

        acc = 1.0 if results[0].strip() == gold else 0.0

        return {
            "acc": acc,
        }

    def higher_is_better(self):
        return {
            "acc": True,
        }

    def aggregation(self):
        return {
            "acc": mean,
        }


class AdvExt(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "AdvExt")

class AnaGen(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "AnaGen")

class CritPred(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "CritPred")

class PDRC(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "PDRC")

class ReadCom(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "ReadCom")

class PoeGen(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "PoeGen")

class PoePred(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "PoePred")

class TPoe(Matching):
    DATASET_PATH = os.path.join(DATASET_PATH, "TPoe")


class Recognition(LocalJsonTask):
    VERSION = 1
    DATASET_PATH = None
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def should_decontaminate(self):
        return True

    def doc_to_decontamination_query(self, doc):
        return doc["text"]

    def doc_to_text(self, doc):

        return doc["query"]

    def construct_requests(self, doc, ctx):
        
        cont_request = rf.greedy_until(ctx, {"until": None})
        return cont_request

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        text = doc["text"]
        pred = process_text(results[0], text)
        

        return {"entity_f1": (pred, doc["label"], results[0])}

    def higher_is_better(self):
        return {
            "entity_f1": True,
        }

    @classmethod
    def entity_f1(cls, items):
        preds, golds, _ = zip(*items)
        f1 = entity_score(golds, preds)

        return f1

    def aggregation(self):
        return {
            "entity_f1": self.entity_f1,
        }


class CLNER(Recognition):
    DATASET_PATH = os.path.join(DATASET_PATH, "CLNER")

    def process_results(self, doc, results):
        text = ' '.join(doc["text"])
        pred = process_zhtext(results[0], text)

        return {"entity_f1": (pred, doc["label"], results[0])}
