import sys
import os
import re
import shutil
import requests
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMenu,
    QFileDialog,
    QMessageBox,
    QStyleOptionSpinBox,
    QStyle,
)
from PySide6.QtCore import (
    Qt,
    QThread,
    Signal,
    QSize,
    QRect,
    QPoint,
    QThreadPool,
    QRunnable,
    QObject,
)
from PySide6.QtGui import QPixmap, QFont, QColor, QPainter, QAction

try:
    from musicdl import musicdl

    MUSICDL_AVAILABLE = True
except ImportError:
    musicdl = None
    MUSICDL_AVAILABLE = False
    print("警告：musicdl 库未安装，请运行 pip install musicdl")


def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "_", str(filename))


# ================= 自定义现代 UI 组件 (保留原样) =================
class ModernComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#6b7280"))
        font = self.font()
        font.setPixelSize(10)
        painter.setFont(font)
        rect = self.rect()
        painter.drawText(
            rect.adjusted(0, 0, -10, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "▼",
        )
        painter.end()


class ModernSpinBox(QSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self.font()
        font.setPixelSize(10)
        painter.setFont(font)
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)

        up_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox, opt, QStyle.SubControl.SC_SpinBoxUp, self
        )
        down_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox,
            opt,
            QStyle.SubControl.SC_SpinBoxDown,
            self,
        )

        draw_up_rect = up_rect.translated(0, 2)
        draw_down_rect = down_rect.translated(0, -2)

        up_pressed = opt.activeSubControls == QStyle.SubControl.SC_SpinBoxUp and (
            opt.state & QStyle.StateFlag.State_Sunken
        )
        down_pressed = opt.activeSubControls == QStyle.SubControl.SC_SpinBoxDown and (
            opt.state & QStyle.StateFlag.State_Sunken
        )

        painter.setPen(QColor("#0078d4") if up_pressed else QColor("#4b5563"))
        painter.drawText(draw_up_rect, Qt.AlignmentFlag.AlignCenter, "▲")
        painter.setPen(QColor("#0078d4") if down_pressed else QColor("#4b5563"))
        painter.drawText(draw_down_rect, Qt.AlignmentFlag.AlignCenter, "▼")
        painter.end()


# ================= [优化 1] 引入线程池处理图片下载 =================
class ImageWorkerSignals(QObject):
    """QRunnable 不能直接发信号，需要借助 QObject"""

    finished = Signal(int, QPixmap)
    error = Signal(int)


class ImageDownloadTask(QRunnable):
    """使用 QRunnable 放入线程池，避免瞬间开启几十个 QThread 导致程序崩溃/内存泄漏"""

    def __init__(self, row, image_url):
        super().__init__()
        self.row = row
        self.image_url = image_url
        self.signals = ImageWorkerSignals()

    def run(self):
        try:
            if not self.image_url:
                self.signals.error.emit(self.row)
                return
            response = requests.get(
                self.image_url, timeout=5
            )  # [优化] 缩短超时时间避免死等
            if response.status_code == 200:
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                scaled_pixmap = pixmap.scaled(
                    44,
                    44,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.signals.finished.emit(self.row, scaled_pixmap)
            else:
                self.signals.error.emit(self.row)
        except Exception:
            self.signals.error.emit(self.row)


# ================= 后台搜索与下载线程 =================
class SearchThread(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, music_client, keyword, search_type):
        super().__init__()
        self.music_client = music_client
        self.keyword = keyword
        self.search_type = search_type

    def run(self):
        try:
            if self.search_type == "搜索歌曲":
                results = self.music_client.search(keyword=self.keyword)
            else:
                results = self.music_client.parseplaylist(self.keyword)
                if not isinstance(results, dict):
                    results = {"歌单": results}
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class DownloadThread(QThread):
    finished = Signal(int)
    error = Signal(str)

    def __init__(self, music_client, song_infos, target_dir):
        super().__init__()
        self.music_client = music_client
        self.song_infos = song_infos
        self.target_dir = target_dir

    def _get_val(self, obj, key, default=""):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default) if hasattr(obj, key) else default

    def run(self):
        try:
            downloaded_songs = self.music_client.download(song_infos=self.song_infos)
            success_count = 0

            for song in downloaded_songs:
                save_path = self._get_val(song, "save_path")
                if not save_path or not os.path.exists(save_path):
                    continue

                song_name = self._get_val(song, "song_name", "未知歌曲")
                singers = self._get_val(song, "singers", "未知歌手")
                if isinstance(singers, list):
                    singer = "&".join([str(s) for s in singers])
                else:
                    singer = str(singers)

                album = self._get_val(song, "album", "")
                identifier = self._get_val(song, "identifier", "")

                ext = os.path.splitext(save_path)[1].lstrip(".")
                if not ext:
                    ext = self._get_val(song, "ext", "mp3")

                parts = [song_name, singer]
                if album:
                    parts.append(str(album))
                if identifier:
                    parts.append(str(identifier))

                base_name = sanitize_filename("-".join(parts))
                new_audio_name = f"{base_name}.{ext}"
                new_audio_path = os.path.join(self.target_dir, new_audio_name)

                # [优化 4] 防止同名文件覆盖报错
                try:
                    if os.path.exists(new_audio_path):
                        os.remove(new_audio_path)
                    shutil.move(save_path, new_audio_path)
                    success_count += 1
                except Exception as e:
                    print(f"移动音频文件失败 {save_path}: {e}")

                old_lrc_path = os.path.splitext(save_path)[0] + ".lrc"
                if os.path.exists(old_lrc_path):
                    new_lrc_name = f"{base_name}.lrc"
                    new_lrc_path = os.path.join(self.target_dir, new_lrc_name)
                    try:
                        if os.path.exists(new_lrc_path):
                            os.remove(new_lrc_path)
                        shutil.move(old_lrc_path, new_lrc_path)
                    except Exception as e:
                        print(f"移动歌词文件失败: {e}")

            self.finished.emit(success_count)
        except Exception as e:
            self.error.emit(str(e))


class SimpleProgressDialog(QDialog):
    def __init__(self, title, message, save_dir=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(360, 130)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet("""
            QDialog { background-color: #ffffff; border: 1px solid #d1d5db; border-radius: 10px; }
        """)
        if parent:
            self.move(
                parent.x() + (parent.width() - self.width()) // 2,
                parent.y() + (parent.height() - self.height()) // 2,
            )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        label = QLabel(message)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 11pt; color: #1f2937; font-weight: bold;")
        layout.addWidget(label)

        if save_dir:
            dir_label = QLabel(f"保存到：{save_dir}")
            dir_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dir_label.setStyleSheet("font-size: 9pt; color: #6b7280;")
            dir_label.setWordWrap(True)
            layout.addWidget(dir_label)

        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setStyleSheet("""
            QProgressBar { border: none; border-radius: 4px; background-color: #f3f4f6; height: 6px; }
            QProgressBar::chunk { background-color: #0078d4; border-radius: 4px; }
        """)
        layout.addWidget(progress)


class FlowLayout(QLayout):
    # (流式布局代码较长，未修改，保持原样)
    def __init__(self, parent=None, margin=-1, hspacing=-1, vspacing=-1):
        super(FlowLayout, self).__init__(parent)
        self._item_list = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def horizontalSpacing(self):
        return (
            self._hspacing
            if self._hspacing >= 0
            else self.smartSpacing(QStyle.PixelMetric.PM_LayoutHorizontalSpacing)
        )

    def verticalSpacing(self):
        return (
            self._vspacing
            if self._vspacing >= 0
            else self.smartSpacing(QStyle.PixelMetric.PM_LayoutVerticalSpacing)
        )

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        return self._item_list[index] if 0 <= index < len(self._item_list) else None

    def takeAt(self, index):
        return self._item_list.pop(index) if 0 <= index < len(self._item_list) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.calculateHeight(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super(FlowLayout, self).setGeometry(rect)
        self.calculateHeight(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def calculateHeight(self, rect, testOnly):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x, y = effective.x(), effective.y()
        lineHeight = 0
        for item in self._item_list:
            widget = item.widget()
            spaceX = self.horizontalSpacing()
            if spaceX == -1:
                spaceX = widget.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Horizontal,
                )
            spaceY = self.verticalSpacing()
            if spaceY == -1:
                spaceY = widget.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Vertical,
                )
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > effective.right() and lineHeight > 0:
                x, y = effective.x(), y + lineHeight + spaceY
                nextX, lineHeight = x + item.sizeHint().width() + spaceX, 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x, lineHeight = nextX, max(lineHeight, item.sizeHint().height())
        return y + lineHeight - rect.y() + margins.bottom()

    def smartSpacing(self, pm):
        parent = self.parent()
        if not parent:
            return -1
        if isinstance(parent, QWidget):
            return parent.style().pixelMetric(pm, None, parent)
        elif isinstance(parent, QLayout):
            return parent.spacing()
        return -1


# 主窗口
class MusicDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎵 音乐下载器")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        font = QFont("Microsoft YaHei", 10)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        QApplication.setFont(font)
        self.setStyleSheet(self.get_modern_style())

        self.source_map_cn_to_en = {
            "苹果音乐": "AppleMusicClient",
            "Deezer": "DeezerMusicClient",
            "5sing": "FiveSingMusicClient",
            "Jamendo": "JamendoMusicClient",
            "Joox": "JooxMusicClient",
            "酷我音乐": "KuwoMusicClient",
            "酷狗音乐": "KugouMusicClient",
            "咪咕音乐": "MiguMusicClient",
            "网易云音乐": "NeteaseMusicClient",
            "QQ音乐": "QQMusicClient",
            "千千音乐": "QianqianMusicClient",
            "Qobuz": "QobuzMusicClient",
            "SoundCloud": "SoundCloudMusicClient",
            "StreetVoice": "StreetVoiceMusicClient",
            "汽水音乐": "SodaMusicClient",
            "Spotify": "SpotifyMusicClient",
            "TIDAL": "TIDALMusicClient",
        }
        self.source_map_en_to_cn = {v: k for k, v in self.source_map_cn_to_en.items()}

        self.search_results = {}
        self.music_records = {}
        self.music_client = None
        self.current_right_click_row = -1

        # [优化 1] 初始化全局线程池，控制最大并发数防止卡死
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(10)

        self.current_dir = os.getcwd()
        self.save_dir = os.path.join(self.current_dir, "已下载音乐")
        os.makedirs(self.save_dir, exist_ok=True)

        self.auto_download_after_search = False

        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        self.setup_top(main_layout)
        self.setup_table(main_layout)

        if not MUSICDL_AVAILABLE:
            QMessageBox.warning(
                self, "警告", "musicdl 库未安装！\n请运行: pip install musicdl"
            )

    def get_modern_style(self):
        # 样式表太长省略部分重复内容，保留核心
        return """
        #CentralWidget { background-color: #f3f4f6; }
        QGroupBox { font-size: 11pt; font-weight: bold; color: #1f2937; background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 14px; padding-bottom: 6px; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #0078d4; }
        QCheckBox { padding: 2px; color: #4b5563; }
        QCheckBox:hover { color: #0078d4; }
        QLineEdit, ModernComboBox, ModernSpinBox { border: 1px solid #d1d5db; border-radius: 6px; padding: 4px 10px; background: #ffffff; min-height: 24px; color: #1f2937; }
        QLineEdit:focus, ModernComboBox:focus, ModernSpinBox:focus { border: 1px solid #0078d4; }
        ModernComboBox::drop-down { width: 24px; border: none; background: transparent; }
        ModernComboBox::down-arrow { image: none; }
        ModernComboBox QAbstractItemView { border: 1px solid #d1d5db; border-radius: 6px; background-color: #ffffff; selection-background-color: #e0f2fe; selection-color: #0369a1; outline: none; padding: 2px; }
        ModernComboBox QAbstractItemView::item { min-height: 28px; border-radius: 4px; padding-left: 6px; }
        ModernSpinBox { padding-right: 22px; }
        ModernSpinBox::up-button, ModernSpinBox::down-button { subcontrol-origin: border; width: 20px; border-left: 1px solid transparent; background: transparent; }
        ModernSpinBox::up-button { subcontrol-position: top right; border-bottom: 1px solid transparent; border-top-right-radius: 5px; }
        ModernSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 5px; }
        ModernSpinBox::up-button:hover, ModernSpinBox::down-button:hover { background: #f3f4f6; }
        ModernSpinBox::up-arrow, ModernSpinBox::down-arrow { image: none; }
        QPushButton { border: none; border-radius: 6px; padding: 6px 16px; background-color: #0078d4; color: white; font-weight: bold; font-size: 10pt; }
        QPushButton:hover { background-color: #1089e5; }
        QPushButton:pressed { background-color: #005a9e; }
        QPushButton:disabled { background-color: #9ca3af; color: #f3f4f6; }
        QPushButton#SearchBtn { background-color: #10b981; }
        QPushButton#SearchBtn:hover { background-color: #059669; }
        QTableWidget { border: 1px solid #e5e7eb; border-radius: 8px; background: #ffffff; alternate-background-color: #f9fafb; color: #374151; selection-background-color: #e0f2fe; selection-color: #0369a1; outline: none; }
        QHeaderView::section { background: #f3f4f6; color: #4b5563; font-weight: bold; border: none; border-bottom: 1px solid #e5e7eb; border-right: 1px solid #e5e7eb; padding: 6px 8px; }
        QTableWidget::item { padding: 2px; border-bottom: 1px solid #f3f4f6; }
        QScrollBar:vertical { border: none; background: #f3f4f6; width: 8px; border-radius: 4px; }
        QScrollBar::handle:vertical { background: #d1d5db; min-height: 20px; border-radius: 4px; }
        QScrollBar::handle:vertical:hover { background: #9ca3af; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """

    def setup_top(self, parent_layout):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        group = QGroupBox("选择音乐源")
        flow = FlowLayout()
        self.source_checkboxes = []
        default_checked = ["酷我音乐", "酷狗音乐"]
        for cn_name in self.source_map_cn_to_en.keys():
            cb = QCheckBox(cn_name)
            if cn_name in default_checked:
                cb.setChecked(True)
            self.source_checkboxes.append(cb)
            flow.addWidget(cb)
        group.setLayout(flow)
        layout.addWidget(group)

        h1 = QHBoxLayout()
        label_limit = QLabel("单源获取数量：")
        self.spin_limit = ModernSpinBox()
        self.spin_limit.setRange(1, 100)
        self.spin_limit.setValue(10)
        self.spin_limit.setSuffix(" 条")
        self.spin_limit.setFixedWidth(100)

        label_save = QLabel("保存目录：")
        self.save_dir_edit = QLineEdit(self.save_dir)
        self.save_dir_edit.setReadOnly(True)
        self.btn_browse = QPushButton("📁 浏览...")
        self.btn_browse.clicked.connect(self.on_browse_save_dir)

        self.check_auto_download = QCheckBox("🚀 搜索后自动下载全部")
        self.check_auto_download.setStyleSheet("font-weight: bold; color: #dc2626;")
        self.check_auto_download.stateChanged.connect(self.on_auto_download_toggle)

        h1.addWidget(label_limit)
        h1.addWidget(self.spin_limit)
        h1.addSpacing(15)
        h1.addWidget(label_save)
        h1.addWidget(self.save_dir_edit, 1)
        h1.addWidget(self.btn_browse)
        h1.addSpacing(15)
        h1.addWidget(self.check_auto_download)
        layout.addLayout(h1)

        h2 = QHBoxLayout()
        self.search_mode = ModernComboBox()
        self.search_mode.addItems(["搜索歌曲", "解析歌单链接"])
        self.search_mode.setFixedWidth(130)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "请输入关键词或输入歌单链接，按回车键也可搜索..."
        )
        self.search_edit.returnPressed.connect(self.on_search)

        self.btn_search = QPushButton("🔍 立即搜索")
        self.btn_search.setObjectName("SearchBtn")
        self.btn_search.setFixedWidth(110)
        self.btn_search.clicked.connect(self.on_search)

        h2.addWidget(self.search_mode)
        h2.addWidget(self.search_edit)
        h2.addWidget(self.btn_search)
        layout.addLayout(h2)
        parent_layout.addLayout(layout)

    def setup_table(self, parent_layout):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        batch = QHBoxLayout()
        scope_label = QLabel("下载范围：")
        self.combo_download_scope = ModernComboBox()
        self.combo_download_scope.addItems(["勾选", "全选", "未勾选"])
        self.combo_download_scope.setFixedWidth(110)

        self.btn_download = QPushButton("⬇️ 下载选中内容")
        self.btn_download.clicked.connect(self.on_download)
        self.btn_download.setEnabled(False)

        batch.addWidget(scope_label)
        batch.addWidget(self.combo_download_scope)
        batch.addStretch()
        batch.addWidget(self.btn_download)
        layout.addLayout(batch)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(9)
        self.results_table.setHorizontalHeaderLabels(
            [
                "选择",
                "专辑封面",
                "歌曲名",
                "歌手",
                "专辑",
                "格式",
                "大小",
                "时长",
                "来源",
            ]
        )
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setShowGrid(False)
        self.results_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(
            self.show_table_context_menu
        )

        self.results_table.setColumnWidth(0, 40)
        self.results_table.setColumnWidth(1, 65)
        self.results_table.setColumnWidth(2, 280)
        self.results_table.setColumnWidth(3, 160)
        self.results_table.setColumnWidth(4, 200)
        self.results_table.setColumnWidth(5, 60)
        self.results_table.setColumnWidth(6, 80)
        self.results_table.setColumnWidth(7, 70)
        self.results_table.verticalHeader().setDefaultSectionSize(54)

        layout.addWidget(self.results_table)
        parent_layout.addLayout(layout)

    def on_auto_download_toggle(self, state):
        self.auto_download_after_search = state == Qt.CheckState.Checked

    # 右键菜单等保持原样...
    def show_table_context_menu(self, pos):
        item = self.results_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        self.current_right_click_row = row

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: white; border: 1px solid #e5e7eb; border-radius: 6px; } QMenu::item { padding: 4px 20px; color: #374151; } QMenu::item:selected { background-color: #0078d4; color: white; }"
        )

        song_name_item = self.results_table.item(row, 2)
        singer_item = self.results_table.item(row, 3)
        action_text = (
            f"📥 下载：{song_name_item.text()} - {singer_item.text()}"
            if (song_name_item and singer_item)
            else "📥 下载此歌曲"
        )

        download_action = QAction(action_text, self)
        download_action.triggered.connect(self.download_current_row)
        menu.addAction(download_action)
        menu.addSeparator()

        select_all_action = QAction("☑️ 全选所有歌曲", self)
        select_all_action.triggered.connect(self.select_all_songs)
        menu.addAction(select_all_action)

        deselect_all_action = QAction("🔲 取消全选", self)
        deselect_all_action.triggered.connect(self.deselect_all_songs)
        menu.addAction(deselect_all_action)

        menu.exec(self.results_table.mapToGlobal(pos))

    def download_current_row(self):
        # 原样
        if self.current_right_click_row < 0 or not self.music_client:
            return
        if str(self.current_right_click_row) not in self.music_records:
            return
        song_info = self.music_records[str(self.current_right_click_row)]
        song_name = song_info.get("song_name", "未知歌曲")
        singers = ", ".join(song_info.get("singers", []))

        reply = QMessageBox.question(
            self,
            "确认下载",
            f"确定要下载这首歌曲吗？\n\n🎵 {song_name} - {singers}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._start_download_task([song_info], f"正在处理：{song_name}")

    def select_all_songs(self):
        for row in range(self.results_table.rowCount()):
            cell_widget = self.results_table.cellWidget(row, 0)
            if cell_widget:
                # Use a lowercase variable name 'checkbox'
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(True)

    def deselect_all_songs(self):
        for row in range(self.results_table.rowCount()):
            cell_widget = self.results_table.cellWidget(row, 0)
            if cell_widget:
                # Use a lowercase variable name 'checkbox'
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)

    def on_browse_save_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择保存/导出目录", self.current_dir
        )
        if dir_path:
            self.save_dir = dir_path
            self.save_dir_edit.setText(dir_path)

    def init_music_client(self):
        if not MUSICDL_AVAILABLE:
            return None
        os.makedirs(self.save_dir, exist_ok=True)
        temp_work_dir = os.path.join(self.current_dir, ".musicdl_temp")
        os.makedirs(temp_work_dir, exist_ok=True)

        src_names = self.get_selected_sources()
        if not src_names:
            QMessageBox.warning(self, "提示", "请至少选择一个音乐来源！")
            return None

        cfg = {
            src: {
                "search_size_per_source": self.spin_limit.value(),
                "work_dir": temp_work_dir,
            }
            for src in src_names
        }
        try:
            if musicdl:
                return musicdl.MusicClient(
                    music_sources=src_names, init_music_clients_cfg=cfg
                )
            return None
        except Exception as e:
            QMessageBox.critical(self, "错误", f"初始化 musicdl 客户端失败：{str(e)}")
            return None

    def get_selected_sources(self):
        return [
            self.source_map_cn_to_en[cb.text()]
            for cb in self.source_checkboxes
            if cb.isChecked()
        ]

    def get_file_format(self, song_info):
        for field in ["format", "ext", "file_format", "type"]:
            if song_info.get(field):
                return str(song_info[field]).upper()
        url = song_info.get("download_url", "").lower()
        for ext in ["mp3", "flac", "wav", "m4a", "aac"]:
            if f".{ext}" in url:
                return ext.upper()
        return "未知"

    def get_album_image_url(self, song_info):
        for field in [
            "cover",
            "album_cover",
            "pic",
            "picture",
            "img",
            "image",
            "album_img",
            "album_pic",
            "cover_url",
            "pic_url",
        ]:
            url = str(song_info.get(field, ""))
            if url.startswith("http"):
                return url
        return ""

    def load_table_with_results(self, search_results):
        self.results_table.setRowCount(0)
        self.search_results = search_results
        self.music_records = {}

        # [优化 2] 清理线程池排队任务（如果有旧的未完成的搜索任务图）
        self.thread_pool.clear()

        all_songs = []
        for per_source in search_results.values():
            all_songs.extend(per_source)

        self.results_table.setRowCount(len(all_songs))
        row = 0
        for _, per_source_search_results in search_results.items():
            for per_source_search_result in per_source_search_results:
                # Checkbox
                w = QWidget()
                lay = QHBoxLayout(w)
                lay.addWidget(QCheckBox())
                lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.setContentsMargins(0, 0, 0, 0)
                self.results_table.setCellWidget(row, 0, w)

                song_name = per_source_search_result.get("song_name", "")
                singers = per_source_search_result.get("singers", "")
                album = per_source_search_result.get("album", "")
                source_cn = self.source_map_en_to_cn.get(
                    per_source_search_result.get("source", ""), ""
                )

                items = [
                    "",
                    "",
                    str(song_name),
                    str(singers),
                    str(album),
                    self.get_file_format(per_source_search_result),
                    str(per_source_search_result.get("file_size", "")),
                    str(per_source_search_result.get("duration", "")),
                    str(source_cn),
                ]

                for column, text in enumerate(items):
                    if column in [0, 1]:
                        continue
                    table_item = QTableWidgetItem(text)
                    align = (
                        Qt.AlignmentFlag.AlignLeft
                        if column in [2, 3, 4]
                        else Qt.AlignmentFlag.AlignHCenter
                    )
                    table_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | align)
                    self.results_table.setItem(row, column, table_item)

                self.music_records[str(row)] = per_source_search_result

                # [优化 1] 将图片下载投递到线程池，而不是直接 new QThread
                album_image_url = self.get_album_image_url(per_source_search_result)
                if album_image_url:
                    task = ImageDownloadTask(row, album_image_url)
                    task.signals.finished.connect(self.on_image_downloaded)
                    task.signals.error.connect(self.on_image_error)
                    self.thread_pool.start(task)
                else:
                    self.on_image_error(row)

                row += 1

        self.btn_download.setEnabled(row > 0)

        if self.auto_download_after_search and all_songs:
            self._start_download_task(all_songs, f"正在处理 {len(all_songs)} 首歌曲")
        else:
            QMessageBox.information(
                self,
                "搜索完毕",
                f"🎉 搜索完成！共找到 {row} 首歌曲。\n(专辑封面正在后台加载...)",
            )

    def _start_download_task(self, songs_list, msg):
        """[优化] 提取出公共的下载弹窗逻辑"""
        dlg = SimpleProgressDialog("下载提取中", msg, self.save_dir, self)
        dlg.show()

        self.download_thread = DownloadThread(
            self.music_client, songs_list, self.save_dir
        )

        def on_finished(success_count):
            dlg.accept()
            QMessageBox.information(
                self,
                "下载完成",
                f"✅ 成功提取 {success_count} 首歌曲！\n已保存在：{self.save_dir}",
            )

        def on_error(error_msg):
            dlg.accept()
            QMessageBox.critical(self, "错误", f"❌ 下载失败：{error_msg}")

        self.download_thread.finished.connect(on_finished)
        self.download_thread.error.connect(on_error)
        self.download_thread.start()

    def on_image_downloaded(self, row, pixmap):
        try:
            label = QLabel()
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("border-radius: 3px;")
            self.results_table.setCellWidget(row, 1, label)
        except Exception as e:
            print(f"设置专辑封面失败: {e}")

    def on_image_error(self, row):
        try:
            label = QLabel("🎵")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("font-size: 20px; color: #d1d5db;")
            self.results_table.setCellWidget(row, 1, label)
        except Exception as e:
            print(f"设置专辑封面失败: {e}")

    def get_songs_by_download_scope(self):
        scope = self.combo_download_scope.currentText()
        songs = []
        for row in range(self.results_table.rowCount()):
            cell_widget = self.results_table.cellWidget(row, 0)
            if not cell_widget:
                continue
            checkbox = cell_widget.findChild(QCheckBox)
            is_checked = checkbox.isChecked() if checkbox else False
            if (
                scope == "全选"
                or (scope == "勾选" and is_checked)
                or (scope == "未勾选" and not is_checked)
            ):
                if str(row) in self.music_records:
                    songs.append(self.music_records[str(row)])
        return songs

    def on_search(self):
        keyword = self.search_edit.text().strip()
        if not keyword:
            QMessageBox.warning(self, "提示", "请输入你要搜索的关键词！")
            return

        self.music_client = self.init_music_client()
        if not self.music_client:
            return

        # [优化 3] 搜索时禁用按钮防止重复点击引发异常
        self.btn_search.setEnabled(False)
        self.btn_search.setText("搜索中...")

        dlg = SimpleProgressDialog(
            "🔍 搜索中", "正在全网搜罗音乐，请稍候...", None, self
        )
        dlg.show()

        self.search_thread = SearchThread(
            self.music_client, keyword, self.search_mode.currentText()
        )

        def on_finished(results):
            dlg.accept()
            self.btn_search.setEnabled(True)
            self.btn_search.setText("🔍 立即搜索")
            self.load_table_with_results(results)

        def on_error(error_msg):
            dlg.accept()
            self.btn_search.setEnabled(True)
            self.btn_search.setText("🔍 立即搜索")
            QMessageBox.critical(self, "错误", f"搜索失败：{error_msg}")

        self.search_thread.finished.connect(on_finished)
        self.search_thread.error.connect(on_error)
        self.search_thread.start()

    def on_download(self):
        if not self.music_client:
            return
        songs_to_download = self.get_songs_by_download_scope()
        if not songs_to_download:
            QMessageBox.warning(self, "提示", "没有符合条件的歌曲，请检查是否已勾选！")
            return

        reply = QMessageBox.question(
            self,
            "确认下载",
            f"确定要下载选中的 {len(songs_to_download)} 首歌曲吗？\n保存目录：{self.save_dir}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_download_task(
                songs_to_download, f"正在批量下载 {len(songs_to_download)} 首歌曲..."
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MusicDownloader()
    win.show()
    sys.exit(app.exec())
