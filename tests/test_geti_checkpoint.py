import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from lightning.pytorch import LightningModule, Trainer
from torch.utils.data import DataLoader, TensorDataset

from workbench.geti_worker import train


class SmallModel(LightningModule):
    def __init__(self):
        super().__init__()
        self.layer = torch.nn.Linear(1, 1)

    def training_step(self, batch, batch_index):
        return self.layer(batch[0]).square().mean()

    def configure_optimizers(self):
        return torch.optim.SGD(self.parameters(), lr=0.01)


class CheckpointTests(unittest.TestCase):
    def test_experiment_saves_final_epoch_with_sparse_validation_schedule(self):
        model = SmallModel()
        engine = SimpleNamespace(checkpoint="")

        def fit(**options):
            trainer = Trainer(accelerator="cpu", devices=1, max_epochs=options["max_epochs"],
                check_val_every_n_epoch=4, limit_val_batches=options["limit_val_batches"],
                callbacks=options["callbacks"], logger=options["logger"],
                enable_progress_bar=False, enable_model_summary=False)
            loader = DataLoader(TensorDataset(torch.ones(24, 1)), batch_size=2)
            trainer.fit(model, train_dataloaders=loader)
            engine.checkpoint = trainer.checkpoint_callback.best_model_path
            return {"epochs": torch.tensor(trainer.current_epoch)}

        engine.train = fit
        module = ModuleType("getitune.engine")
        module.create_engine = lambda **kwargs: engine
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            args = SimpleNamespace(data=output, output=output, device="cpu", epochs=30, experimental=True, batch_size=2)
            with patch.dict("sys.modules", {"getitune.engine": module}), \
                 patch("workbench.geti_worker.make_data", return_value=SimpleNamespace(label_info=SimpleNamespace(label_names=["缺角"]))), \
                 patch("workbench.geti_worker.make_model", return_value=model):
                train(args)
            checkpoint = torch.load(output / "model.ckpt", map_location="cpu", weights_only=False)
            self.assertEqual(checkpoint["epoch"], 29)
            self.assertEqual(checkpoint["global_step"], 360)
            metadata = json.loads((output / "model.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["labels"], ["缺角"])
            self.assertTrue(metadata["experimental"])
