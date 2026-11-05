from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.output_naming import sanitize_label
from app.gui.app_paths import local_data_dir
from app.gui.dialogs.apply_macro_dialog import (
    LoadMacroDialog,
    LoadMacroRequest,
    SavedMacroPickDialog,
)
from app.gui.dialogs.loading_progress_dialog import LoadingProgressDialog
from app.gui.form_controls import create_form_combobox
from app.gui.folder_utils import open_in_file_manager
from app.gui.theme import mark_page_subtitle, mark_page_title, mark_primary_button, mark_secondary_button
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.workers.vpe_macro_worker import VpeMacroJob, VpeMacroResult, VpeMacroWorker
from app.modules.vpe_macro.apm_macro import AccessProfileRef, MacroSnapshot, MacroSummary
from app.modules.vpe_macro.store import MacroSnapshotStore

_PROFILE_PLACEHOLDER = "Access Profile을 선택하세요"


def _pick_macro_json(parent: QWidget, *, title: str, start: str, save: bool) -> str:
    """Qt 파일 창만 사용. Windows 네이티브 열기 직후 다음 창을 띄우면 exe가 죽는 경우가 있다."""
    dialog = QFileDialog(parent, title, start, "Macro JSON (*.json)")
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setNameFilter("Macro JSON (*.json)")
    if save:
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("json")
    else:
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    files = dialog.selectedFiles()
    return files[0] if files else ""


class VpeMacroView(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.data_dir = local_data_dir()
        self.store = MacroSnapshotStore(self.data_dir)
        self._worker: VpeMacroWorker | None = None
        self._host = ""
        self._port = 443
        self._username = ""
        self._password = ""
        self._hostname = ""
        self._connected = False
        self._profiles: list[AccessProfileRef] = []
        self._current_profile: AccessProfileRef | None = None
        self._macros: list[MacroSummary] = []
        self._items: list[dict] = []
        self._policy: dict = {}
        self._snapshot: MacroSnapshot | None = None
        self._pending_after_export: str | None = None
        self._reload_after_apply = False
        self._load_dialog: LoadMacroDialog | None = None
        self._macro_picker: SavedMacroPickDialog | None = None
        self._loading: LoadingProgressDialog | None = None
        self._build_ui()
        self._set_workspace_enabled(False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(280)
        outer.addWidget(scroll, stretch=3)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)

        title = QLabel("VPE Macro Copy")
        mark_page_title(title)
        root.addWidget(title)
        subtitle = QLabel(
            "Test Connection 후 Access Profile을 선택하면 Macro가 표시됩니다. "
            "Save Macro로 파일을 저장하고, Load Macro로 이 장비 또는 다른 장비의 Access Profile에 넣을 수 있습니다. "
            "같은 장비에서는 Macro 이름을 그대로 쓸 수 없습니다. Access Profile이 달라도 이름은 장비 전역에서 유일합니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(False)
        self.status_label.setFixedHeight(22)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )

        self.connection = DeviceConnectionPanel(self.data_dir, tmos_only=True)
        self.connection.status_message.connect(self._set_status_text)
        self.connection.connection_test_finished.connect(self._on_connection_tested)
        self.connection.disconnected.connect(self._on_disconnected)
        root.addWidget(self.connection)

        self.workspace = QWidget()
        work = QVBoxLayout(self.workspace)
        work.setContentsMargins(0, 8, 0, 0)

        profile_box = QGroupBox("Access Profile")
        profile_form = QFormLayout(profile_box)
        row = QHBoxLayout()
        self.profile_combo: QComboBox = create_form_combobox()
        self.refresh_btn = QPushButton("Refresh")
        row.addWidget(self.profile_combo, stretch=1)
        row.addWidget(self.refresh_btn)
        profile_form.addRow("Profile", row)
        work.addWidget(profile_box)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QGroupBox("Macro")
        left_layout = QVBoxLayout(left)
        self.macro_list = QListWidget()
        self.macro_list.setMinimumWidth(220)
        left_layout.addWidget(self.macro_list)
        splitter.addWidget(left)

        right = QGroupBox("Macro 설정")
        right_layout = QVBoxLayout(right)
        self.detail_caption = QLabel(_PROFILE_PLACEHOLDER)
        self.detail_caption.setWordWrap(True)
        right_layout.addWidget(self.detail_caption)
        self.detail_tree = QTreeWidget()
        self.detail_tree.setHeaderLabels(["항목", "값"])
        self.detail_tree.setColumnWidth(0, 160)
        right_layout.addWidget(self.detail_tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setMinimumHeight(220)
        work.addWidget(splitter, stretch=1)

        action_row = QHBoxLayout()
        self.save_btn = QPushButton("Save Macro")
        mark_primary_button(self.save_btn)
        self.load_btn = QPushButton("Load Macro")
        mark_secondary_button(self.load_btn)
        self.open_saved_btn = QPushButton("저장된 폴더")
        action_row.addWidget(self.save_btn)
        action_row.addWidget(self.load_btn)
        action_row.addWidget(self.open_saved_btn)
        action_row.addStretch()
        work.addLayout(action_row)
        root.addWidget(self.workspace)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        outer.addWidget(self.status_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(72)
        self.log_view.setMaximumHeight(96)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_view.setMinimumWidth(0)
        self.log_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.log_view.setPlaceholderText("작업 로그")
        outer.addWidget(self.log_view, stretch=0)

        self.refresh_btn.clicked.connect(self._reload_profiles)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.macro_list.currentRowChanged.connect(self._on_macro_selected)
        self.save_btn.clicked.connect(self._on_save)
        self.load_btn.clicked.connect(self._on_load_saved)
        self.open_saved_btn.clicked.connect(self._open_saved_folder)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown_workers()
        super().closeEvent(event)

    def shutdown_workers(self) -> None:
        self._stop_worker()
        self._close_loading()
        if self._load_dialog is not None:
            self._load_dialog.close()
            self._load_dialog = None
        if self._macro_picker is not None:
            self._macro_picker.close()
            self._macro_picker = None
        self._password = ""
        self.connection._stop_test_worker()

    def _set_status_text(self, message: str) -> None:
        short = " ".join((message or "").split())
        if len(short) > 120:
            short = short[:120] + "…"
        self.status_label.setText(short)

    def _append_log(self, message: str) -> None:
        self.log_view.append(message)
        self._set_status_text(message)

    def _set_workspace_enabled(self, enabled: bool) -> None:
        self.profile_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)

    def _set_busy(self, busy: bool, *, indeterminate: bool = True) -> None:
        # range 0,0 is an animated busy bar. On this Qt build that animation
        # overflows the stack and exits the exe during a long tmsh wait.
        self.progress.setVisible(busy and indeterminate)
        self.progress.setRange(0, 100)
        self.progress.setValue(0 if busy else 100)
        self.progress.setTextVisible(False)
        self.connection.test_btn.setEnabled(not busy)
        self.connection.disconnect_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy and self._connected)
        self.save_btn.setEnabled(not busy and self._connected)
        self.load_btn.setEnabled(not busy)
        self.profile_combo.setEnabled(not busy and self._connected)

    def _open_loading(self, title: str, message: str) -> None:
        self._close_loading()
        dialog = LoadingProgressDialog(title, message, self)
        self._loading = dialog
        dialog.show()

    def _update_loading(self, current: int, total: int, detail: str = "") -> None:
        if self._loading is not None:
            self._loading.set_progress(current, total, detail)

    def _finish_loading(self) -> None:
        dialog = self._loading
        self._loading = None
        if dialog is not None:
            dialog.finish()

    def _close_loading(self) -> None:
        dialog = self._loading
        self._loading = None
        if dialog is not None:
            dialog.fail_and_close()

    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        for signal in (worker.progress, worker.percent, worker.finished_ok, worker.failed):
            try:
                signal.disconnect()
            except TypeError:
                pass
        if worker.isRunning() and worker is not self.sender():
            worker.requestInterruption()
            worker.wait(3000)

    def _on_worker_ok(self, result: object) -> None:
        self._worker = None
        self._set_busy(False)
        if not isinstance(result, VpeMacroResult):
            self._close_loading()
            return
        if result.action == "login":
            self._on_login_ok(result)
            self._finish_loading()
        elif result.action == "load_macros":
            self._close_loading()
            self._on_macros_ok(result)
        elif result.action == "export":
            self._close_loading()
            self._on_export_ok(result)
        elif result.action == "apply":
            self._close_loading()
            self._on_apply_ok(result)

    def _on_worker_fail(self, message: str) -> None:
        self._worker = None
        self._set_busy(False)
        self._close_loading()
        self._pending_after_export = None
        self._reload_after_apply = False
        self._append_log(f"실패: {message}")
        shown = " ".join((message or "").split())
        if len(shown) > 600:
            shown = shown[:600] + "…"
        lines = [shown[i : i + 42] for i in range(0, len(shown), 42)] or [""]
        QMessageBox.critical(self, "VPE Macro", "\n".join(lines))

    def _run_job(self, job: VpeMacroJob, *, loading_title: str | None = None) -> None:
        self._stop_worker()
        if loading_title:
            self.log_view.clear()
            self._open_loading(loading_title, "Access Profile을 불러오는 중입니다…")
            self._set_busy(True, indeterminate=False)
        else:
            self._close_loading()
            self._set_busy(True)
        worker = VpeMacroWorker(job)
        self._worker = worker
        worker.progress.connect(self._append_log)
        if loading_title:
            worker.percent.connect(self._update_loading)
        worker.finished_ok.connect(self._on_worker_ok)
        worker.failed.connect(self._on_worker_fail)
        worker.start()

    def _creds_job(self, action: str, **kwargs) -> VpeMacroJob:
        return VpeMacroJob(
            action=action,  # type: ignore[arg-type]
            host=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            source_hostname=self._hostname,
            **kwargs,
        )

    def _capture_credentials(self) -> bool:
        host, port, user, password = self.connection.tmos_credentials()
        if not host or not user or not password:
            QMessageBox.warning(
                self, "VPE Macro", "TMOS MGMT IP, 사용자 ID, 비밀번호를 입력하세요."
            )
            return False
        self._host = host
        self._port = port
        self._username = user
        self._password = password
        return True

    def _on_connection_tested(self, ok: bool) -> None:
        if not ok:
            return
        if not self._capture_credentials():
            return
        self._connected = True
        self._set_workspace_enabled(True)
        self._fill_profiles([], "")
        self.detail_caption.setText(_PROFILE_PLACEHOLDER)
        self._run_job(self._creds_job("login"), loading_title="Access Profile Loading")

    def _on_disconnected(self) -> None:
        self._close_loading()
        self._connected = False
        self._password = ""
        self._hostname = ""
        self._profiles = []
        self._current_profile = None
        self._macros = []
        self._snapshot = None
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.blockSignals(False)
        self.macro_list.clear()
        self.detail_tree.clear()
        self.detail_caption.setText(_PROFILE_PLACEHOLDER)
        self._set_workspace_enabled(False)
        self.status_label.setText("연결 해제됨")

    def _reload_profiles(self) -> None:
        if not self._connected:
            return
        if not self._capture_credentials():
            return
        self._run_job(self._creds_job("login"), loading_title="Access Profile Loading")

    def _on_profile_changed(self, _index: int) -> None:
        path = str(self.profile_combo.currentData() or "")
        if not path or not self._connected:
            self._current_profile = None
            self._macros = []
            self._items = []
            self._policy = {}
            self._snapshot = None
            self.macro_list.clear()
            self.detail_tree.clear()
            self.detail_caption.setText(_PROFILE_PLACEHOLDER)
            return
        self._run_job(
            self._creds_job(
                "load_macros",
                profile_path=path,
                target_profile=next(
                    (ref for ref in self._profiles if ref.full_path == path),
                    None,
                ),
            )
        )

    def _on_macro_selected(self, _row: int) -> None:
        self._snapshot = None
        macro = self._current_macro()
        if macro is None:
            self.detail_caption.setText("Macro를 선택하세요.")
            self.detail_tree.clear()
            return
        self.detail_caption.setText(
            f"<b>{macro.caption}</b>  ·  {macro.full_path}  ·  items {macro.item_count}"
        )
        self.detail_caption.setTextFormat(Qt.TextFormat.RichText)
        self.detail_tree.clear()
        rows = [
            ("Caption", macro.caption),
            ("Name", macro.name),
            ("Partition", macro.partition),
            ("Full path", macro.full_path),
            ("Exits", ", ".join(macro.exits) or "—"),
            ("Agents", ", ".join(macro.agent_labels) or "—"),
            ("Policy items", str(macro.item_count)),
        ]
        for label, value in rows:
            QTreeWidgetItem(self.detail_tree, [label, value])
        items_root = QTreeWidgetItem(self.detail_tree, ["내부 객체", ""])
        by_path = {
            str(i.get("fullPath") or f"/{i.get('partition', 'Common')}/{i.get('name')}"): i
            for i in self._items
        }
        for path in macro.item_paths:
            item = by_path.get(path) or {}
            kind = str(item.get("itemType") or "")
            cap = str(item.get("caption") or item.get("name") or path)
            QTreeWidgetItem(items_root, [cap, f"{kind}  {path}"])
        self.detail_tree.expandAll()

    def _current_macro(self) -> MacroSummary | None:
        row = self.macro_list.currentRow()
        if row < 0 or row >= len(self._macros):
            return None
        return self._macros[row]

    def _fill_profiles(self, profiles: list[AccessProfileRef], selected_path: str = "") -> None:
        self._profiles = profiles
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem(_PROFILE_PLACEHOLDER, "")
        for ref in profiles:
            self.profile_combo.addItem(ref.full_path, ref.full_path)
        if selected_path:
            idx = self.profile_combo.findData(selected_path)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
            else:
                self.profile_combo.setCurrentIndex(0)
        else:
            self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)

    def _fill_macros(self, macros: list[MacroSummary]) -> None:
        self._macros = macros
        self.macro_list.clear()
        for macro in macros:
            exits = ", ".join(macro.exits)
            label = macro.caption
            if exits:
                label = f"{macro.caption}  ({exits})"
            item = QListWidgetItem(label)
            item.setToolTip(macro.full_path)
            self.macro_list.addItem(item)
        if macros:
            self.macro_list.setCurrentRow(0)
        else:
            self.detail_caption.setText("이 Access Profile에 Macro가 없습니다.")
            self.detail_tree.clear()

    def _on_login_ok(self, result: VpeMacroResult) -> None:
        self._connected = True
        self._hostname = result.hostname
        self._set_workspace_enabled(True)
        keep = str(self.profile_combo.currentData() or "")
        self._fill_profiles(result.profiles, keep)
        self._append_log(f"로그인 성공 — Access Profile {len(result.profiles)}개. {_PROFILE_PLACEHOLDER}.")
        if keep:
            self._run_job(self._creds_job("load_macros", profile_path=keep))
        else:
            self.macro_list.clear()
            self.detail_tree.clear()
            self.detail_caption.setText(_PROFILE_PLACEHOLDER)

    def _on_macros_ok(self, result: VpeMacroResult) -> None:
        self._current_profile = result.selected_profile
        self._policy = result.policy
        self._items = result.items
        if result.profiles:
            current = result.selected_profile.full_path if result.selected_profile else ""
            self._fill_profiles(result.profiles, current)
        self._fill_macros(result.macros)
        name = result.selected_profile.name if result.selected_profile else ""
        self._append_log(f"{name}: Macro {len(result.macros)}개")

    def _on_export_ok(self, result: VpeMacroResult) -> None:
        self._snapshot = result.snapshot
        pending = self._pending_after_export
        self._pending_after_export = None
        if result.snapshot is None:
            QMessageBox.warning(self, "Macro", "Macro 스냅샷을 만들지 못했습니다.")
            return
        if pending == "save":
            self._save_snapshot(result.snapshot)

    def _on_apply_ok(self, result: VpeMacroResult) -> None:
        applied = result.apply_result
        count = len(applied.created_items) if applied else 0
        skipped = len(applied.skipped) if applied else 0
        target = result.selected_profile.full_path if result.selected_profile else ""
        extra = ""
        if applied and applied.messages:
            extra = "\n\n" + "\n".join(applied.messages[:4])
        names = []
        if applied:
            names.extend(applied.created_items)
            names.extend(name for name in applied.skipped if name not in names)
        shown = ", ".join(names) or "Macro"
        if applied and applied.skipped and not applied.created_items:
            summary = f"대상 Access Profile에 기존 Macro를 연결했습니다. ({shown})"
        elif applied and applied.applied_policy:
            summary = f"대상 Access Profile에 Macro를 넣었습니다. ({shown})"
        else:
            summary = f"대상 Access Profile에 Macro를 추가했습니다. (생성 {count}개)"
        link = "Profile에 연결됨" if applied and applied.applied_policy else f"연결 {skipped}"
        self._append_log(f"Load 완료 — {target} (생성 {count}, {link})")
        QMessageBox.information(
            self,
            "Load Macro",
            f"{summary}\n{target}{extra}\n\n"
            "대상 Access Profile VPE Macro 목록에서 저장한 Macro가 보이는지 확인하세요.",
        )
        self._reload_after_apply = False

    def _ensure_macro_selected(self) -> MacroSummary | None:
        macro = self._current_macro()
        if macro is None:
            QMessageBox.information(self, "Macro", "먼저 Macro를 선택하세요.")
        return macro

    def _on_save(self) -> None:
        macro = self._ensure_macro_selected()
        if macro is None or self._current_profile is None:
            return
        self._pending_after_export = "save"
        self._run_job(
            self._creds_job(
                "export",
                profile_path=self._current_profile.full_path,
                macro_path=macro.full_path,
            )
        )

    def _save_snapshot(self, snapshot: MacroSnapshot) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        default = sanitize_label(snapshot.macro_caption or snapshot.macro_full_path or "macro", max_len=80)
        path_str = _pick_macro_json(
            self.window(),
            title="Save Macro — 저장 위치",
            start=str(self.store.root / f"{default}.json"),
            save=True,
        )
        if not path_str:
            return
        path = self.store.save_to_path(snapshot, Path(path_str))
        self._append_log(f"저장됨: {path}")
        QMessageBox.information(
            self,
            "Save Macro",
            f"Macro를 저장했습니다.\n\n{path}\n\n"
            "같은 폴더에서 Load Macro로 불러올 수 있습니다.",
        )

    def _open_load_dialog(self, snapshot: MacroSnapshot) -> None:
        try:
            source = self._current_profile.full_path if self._current_profile else ""
            if self._load_dialog is not None:
                self._load_dialog.close()
                self._load_dialog = None
            dialog = LoadMacroDialog(
                snapshot=snapshot,
                profiles=self._profiles,
                source_profile_path=source,
                this_device_connected=self._connected,
                this_host=self._host,
                this_port=self._port,
                this_username=self._username,
                this_password=self._password,
                parent=self.window(),
            )
            dialog.setModal(False)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.load_requested.connect(self._on_load_requested)
            dialog.destroyed.connect(self._clear_load_dialog)
            self._load_dialog = dialog
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"실패: Load 창 오류 — {exc}")
            QMessageBox.critical(self, "Load Macro", str(exc))

    def _clear_load_dialog(self, _obj=None) -> None:
        self._load_dialog = None

    def _on_load_requested(self, request: object) -> None:
        if not isinstance(request, LoadMacroRequest):
            return
        self._reload_after_apply = (not request.other_device) and self._connected
        self._run_job(
            VpeMacroJob(
                action="apply",
                host=request.host,
                port=request.port,
                username=request.username,
                password=request.password,
                snapshot=request.snapshot,
                target_profile_path=request.target_profile_path,
                target_macro_name=request.target_macro_name,
                source_hostname=self._hostname,
                target_profile=request.target_profile,
            )
        )

    def _on_load_saved(self) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        files = [
            (f"{path.stem}  ({path.name})", str(path))
            for path in sorted(self.store.root.glob("*.json"))
        ]
        if not files:
            QMessageBox.information(
                self,
                "Load Macro",
                "저장된 Macro 파일이 없습니다. 먼저 Save Macro 하세요.",
            )
            return
        picker = SavedMacroPickDialog(files, self.window())
        picker.setModal(False)
        picker.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        picker.file_chosen.connect(self._load_snapshot_path)
        picker.destroyed.connect(lambda _obj=None: setattr(self, "_macro_picker", None))
        self._macro_picker = picker
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _load_snapshot_path(self, path_str: str) -> None:
        try:
            path = Path(path_str)
            if not path.is_file():
                raise FileNotFoundError(path)
            if path.stat().st_size > 2_000_000:
                raise ValueError("Macro 파일이 너무 큽니다 (2MB 초과).")
            snapshot = self.store.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load Macro", str(exc))
            return
        self._snapshot = snapshot
        self._append_log(f"불러옴: {snapshot.macro_caption} ({path.name})")
        QTimer.singleShot(50, lambda: self._open_load_dialog(snapshot))

    def _open_saved_folder(self) -> None:
        open_in_file_manager(self.store.root)
