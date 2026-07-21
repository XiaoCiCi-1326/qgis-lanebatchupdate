# -*- coding: utf-8 -*-
"""Processing 进度回传到对话框。"""

from qgis.core import QgsProcessingFeedback


class ReconstructFeedback(QgsProcessingFeedback):
    def __init__(self, progress_dialog, log_fn):
        super().__init__()
        self.progress_dialog = progress_dialog
        self.log_fn = log_fn

    def pushInfo(self, info, fatalError=False):
        super().pushInfo(info, fatalError)
        text = str(info)
        if self.progress_dialog:
            self.progress_dialog.setLabelText(text)
        self.log_fn(text, show_bar=False)

    def setProgressText(self, text):
        super().setProgressText(text)
        if self.progress_dialog:
            self.progress_dialog.setLabelText(text)
