import sys
import os
import requests
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

# 尝试导入 musicdl
try:
    from musicdl import musicdl
    MUSICDL_AVAILABLE = True
except ImportError:
    MUSICDL_AVAILABLE = False
    print("警告：musicdl 库未安装，请运行 pip install musicdl")

# 图片下载线程
class ImageDownloadThread(QThread):
    finished = pyqtSignal(int, QPixmap)
    error = pyqtSignal(int)
    def __init__(self, row, image_url):
        super().__init__()
        self.row = row
        self.image_url = image_url
    def run(self):
        try:
            if not self.image_url or self.image_url == '':
                self.error.emit(self.row)
                return
            response = requests.get(self.image_url, timeout=10)
            if response.status_code == 200:
                image_data = response.content
                pixmap = QPixmap()
                pixmap.loadFromData(image_data)
                scaled_pixmap = pixmap.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.finished.emit(self.row, scaled_pixmap)
            else:
                self.error.emit(self.row)
        except Exception as e:
            print(f"下载图片失败: {e}")
            self.error.emit(self.row)

# 后台搜索线程
class SearchThread(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
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

# 后台下载线程
class DownloadThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    def __init__(self, music_client, song_infos):
        super().__init__()
        self.music_client = music_client
        self.song_infos = song_infos
    def run(self):
        try:
            self.music_client.download(song_infos=self.song_infos)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

# 自定义简单弹窗（修改：支持显示保存位置）
class SimpleProgressDialog(QDialog):
    def __init__(self, title, message, save_dir=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(360, 120)  # 稍微加大一点以容纳保存位置
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setWindowModality(Qt.ApplicationModal)
        if parent:
            self.move(parent.x() + (parent.width() - self.width()) // 2, parent.y() + (parent.height() - self.height()) // 2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        # 主消息
        label = QLabel(message)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 11pt; color: #2c3e50; font-weight: bold;")
        layout.addWidget(label)
        
        # 【新增】保存位置显示
        if save_dir:
            dir_label = QLabel(f"保存到：{save_dir}")
            dir_label.setAlignment(Qt.AlignCenter)
            dir_label.setStyleSheet("font-size: 9pt; color: #666;")
            dir_label.setWordWrap(True)
            layout.addWidget(dir_label)
        
        # 进度条
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setStyleSheet("""
            QProgressBar { border: none; border-radius: 4px; background-color: #e9ecef; height: 8px; }
            QProgressBar::chunk { background-color: #0078d4; border-radius: 4px; }
        """)
        layout.addWidget(progress)

# 流式布局
class FlowLayout(QLayout):
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
        return self._hspacing if self._hspacing >= 0 else self.smartSpacing(QStyle.PM_LayoutHorizontalSpacing)
    def verticalSpacing(self):
        return self._vspacing if self._vspacing >= 0 else self.smartSpacing(QStyle.PM_LayoutVerticalSpacing)
    def count(self): return len(self._item_list)
    def itemAt(self, index): return self._item_list[index] if 0 <= index < len(self._item_list) else None
    def takeAt(self, index): return self._item_list.pop(index) if 0 <= index < len(self._item_list) else None
    def expandingDirections(self): return Qt.Orientations()
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self.calculateHeight(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect):
        super(FlowLayout, self).setGeometry(rect)
        self.calculateHeight(rect, False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)
    def calculateHeight(self, rect, testOnly):
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        x, y = effective.x(), effective.y()
        lineHeight = 0
        for item in self._item_list:
            widget = item.widget()
            spaceX = self.horizontalSpacing()
            if spaceX == -1:
                spaceX = widget.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal)
            spaceY = self.verticalSpacing()
            if spaceY == -1:
                spaceY = widget.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical)
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > effective.right() and lineHeight > 0:
                x, y = effective.x(), y + lineHeight + spaceY
                nextX, lineHeight = x + item.sizeHint().width() + spaceX, 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x, lineHeight = nextX, max(lineHeight, item.sizeHint().height())
        return y + lineHeight - rect.y() + bottom
    def smartSpacing(self, pm):
        parent = self.parent()
        if not parent: return -1
        return parent.style().pixelMetric(pm, None, parent) if parent.isWidgetType() else parent.spacing()

# 主窗口
class MusicDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("音乐下载器 · 宇宙超级无敌版")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        self.setStyleSheet(self.get_modern_style())
        
        # 音乐源中英文映射
        self.source_map_cn_to_en = {
            "苹果音乐": "AppleMusicClient", "Deezer": "DeezerMusicClient", "5sing": "FiveSingMusicClient",
            "Jamendo": "JamendoMusicClient", "Joox": "JooxMusicClient", "酷我音乐": "KuwoMusicClient",
            "酷狗音乐": "KugouMusicClient", "咪咕音乐": "MiguMusicClient", "网易云音乐": "NeteaseMusicClient",
            "QQ音乐": "QQMusicClient", "千千音乐": "QianqianMusicClient", "Qobuz": "QobuzMusicClient",
            "SoundCloud": "SoundCloudMusicClient", "StreetVoice": "StreetVoiceMusicClient", "汽水音乐": "SodaMusicClient",
            "Spotify": "SpotifyMusicClient", "TIDAL": "TIDALMusicClient"
        }
        self.source_map_en_to_cn = {v: k for k, v in self.source_map_cn_to_en.items()}
        
        # 保存搜索结果
        self.search_results = {}
        self.music_records = {}
        self.music_client = None
        self.image_threads = []
        self.current_right_click_row = -1
        
        # 设置当前路径和保存目录
        self.current_dir = os.getcwd()
        self.save_dir = os.path.join(self.current_dir, "已下载音乐")
        os.makedirs(self.save_dir, exist_ok=True)
        
        # 搜索后直接下载开关
        self.auto_download_after_search = False
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        
        self.setup_top(main_layout)
        self.setup_table(main_layout)
        
        if not MUSICDL_AVAILABLE:
            QMessageBox.warning(self, "警告", "musicdl 库未安装！\n请运行: pip install musicdl")

    def get_modern_style(self):
        return """
        QMainWindow { background-color: #f8f9fa; font-size: 11pt; }
        QGroupBox {
            font-size: 12pt; font-weight: bold; color: #2c3e50;
            border: 1px solid #dce1e6; border-radius: 8px;
            margin-top: 12px; padding-top: 8px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
        QCheckBox { font-size: 11pt; padding: 4px 2px; }
        QLineEdit, QComboBox, QSpinBox {
            font-size: 11pt; border: 1px solid #d1d5db; border-radius: 6px;
            padding: 6px 10px; background: white; min-height: 28px;
        }
        QPushButton {
            font-size: 11pt; border: none; border-radius: 6px; padding: 8px 16px;
            background-color: #0078d4; color: white; font-weight: bold;
        }
        QPushButton:hover { background-color: #1089e5; }
        QPushButton:pressed { background-color: #0063b8; }
        QTableWidget {
            font-size: 11pt; border: 1px solid #e5e7eb; border-radius: 8px;
            background: white; gridline-color: #f3f4f6;
        }
        QHeaderView::section {
            font-size: 11pt; font-weight: bold; background: #e9ecef;
            border: none; padding: 8px;
        }
        QMenu {
            font-size: 11pt; border: 1px solid #d1d5db; border-radius: 6px;
            background: white; padding: 4px;
        }
        QMenu::item {
            padding: 6px 30px 6px 20px; border-radius: 4px;
        }
        QMenu::item:selected { background-color: #e8f0fe; }
        QComboBox QAbstractItemView {
            font-size: 11pt; selection-background-color: #0078d4;
        }
        QDialog { font-size: 11pt; }
        QLabel { font-size: 11pt; }
        """

    def setup_top(self, parent_layout):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        
        # 音乐来源
        group = QGroupBox("音乐来源")
        flow = FlowLayout()
        self.source_checkboxes = []
        for chinese_name in self.source_map_cn_to_en.keys():
            cb = QCheckBox(chinese_name)
            if chinese_name in ["网易云音乐", "QQ音乐", "酷我音乐", "酷狗音乐", "咪咕音乐"]:
                cb.setChecked(True)
            self.source_checkboxes.append(cb)
            flow.addWidget(cb)
        group.setLayout(flow)
        layout.addWidget(group)
        
        # 结果数量限制 + 保存目录 + 自动下载选项
        h1 = QHBoxLayout()
        label_limit = QLabel("结果数量：")
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(1, 100)
        self.spin_limit.setValue(10)
        self.spin_limit.setSuffix(" 条/源")
        
        label_save = QLabel("保存目录：")
        self.save_dir_edit = QLineEdit(self.save_dir)
        self.save_dir_edit.setReadOnly(True)
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.clicked.connect(self.on_browse_save_dir)
        
        # 自动下载复选框
        self.check_auto_download = QCheckBox("🚀 搜索后自动下载全部")
        self.check_auto_download.stateChanged.connect(self.on_auto_download_toggle)
        
        h1.addWidget(label_limit)
        h1.addWidget(self.spin_limit)
        h1.addSpacing(30)
        h1.addWidget(label_save)
        h1.addWidget(self.save_dir_edit)
        h1.addWidget(self.btn_browse)
        h1.addSpacing(30)
        h1.addWidget(self.check_auto_download)
        h1.addStretch()
        layout.addLayout(h1)
        
        # 搜索区域
        h2 = QHBoxLayout()
        self.search_mode = QComboBox()
        self.search_mode.addItems(["搜索歌曲", "解析歌单链接"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入关键词或歌单链接...")
        self.btn_search = QPushButton("搜索")
        self.btn_search.clicked.connect(self.on_search)
        h2.addWidget(self.search_mode)
        h2.addWidget(self.search_edit)
        h2.addWidget(self.btn_search)
        layout.addLayout(h2)
        
        parent_layout.addLayout(layout)

    def setup_table(self, parent_layout):
        layout = QVBoxLayout()
        
        # 下载范围选择
        batch = QHBoxLayout()
        self.combo_download_scope = QComboBox()
        self.combo_download_scope.addItems(["全选", "勾选", "未勾选"])
        self.btn_download = QPushButton("下载选中")
        self.btn_download.clicked.connect(self.on_download)
        self.btn_download.setEnabled(False)
        batch.addWidget(QLabel("下载范围："))
        batch.addWidget(self.combo_download_scope)
        batch.addStretch()
        batch.addWidget(self.btn_download)
        layout.addLayout(batch)
        
        # 歌曲表格
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(9)
        self.results_table.setHorizontalHeaderLabels([
            "选择", "专辑封面", "歌曲名", "歌手", 
            "专辑", "格式", "大小", "时长", "来源"
        ])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        
        # 设置表格属性
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self.show_table_context_menu)
        
        # 设置列宽
        self.results_table.setColumnWidth(0, 60)
        self.results_table.setColumnWidth(1, 70)
        self.results_table.setColumnWidth(2, 240)
        self.results_table.setColumnWidth(3, 140)
        self.results_table.setColumnWidth(4, 190)
        self.results_table.setColumnWidth(5, 60)
        self.results_table.setColumnWidth(6, 90)
        self.results_table.setColumnWidth(7, 70)
        self.results_table.verticalHeader().setDefaultSectionSize(70)
        layout.addWidget(self.results_table)
        
        parent_layout.addLayout(layout)

    # 自动下载开关切换（修改：不改变界面布局）
    def on_auto_download_toggle(self, state):
        self.auto_download_after_search = (state == Qt.Checked)
        # 界面布局保持不变，只记录状态

    def show_table_context_menu(self, pos):
        item = self.results_table.itemAt(pos)
        if not item: return
        row = item.row()
        self.current_right_click_row = row
        
        menu = QMenu(self)
        song_name_item = self.results_table.item(row, 2)
        singer_item = self.results_table.item(row, 3)
        action_text = f"下载：{song_name_item.text()} - {singer_item.text()}" if (song_name_item and singer_item) else "下载此歌曲"
        download_action = QAction(action_text, self)
        download_action.triggered.connect(self.download_current_row)
        menu.addAction(download_action)
        
        menu.addSeparator()
        select_all_action = QAction("全选所有歌曲", self)
        select_all_action.triggered.connect(self.select_all_songs)
        menu.addAction(select_all_action)
        deselect_all_action = QAction("取消全选", self)
        deselect_all_action.triggered.connect(self.deselect_all_songs)
        menu.addAction(deselect_all_action)
        
        menu.exec_(self.results_table.mapToGlobal(pos))

    def download_current_row(self):
        if self.current_right_click_row < 0 or not self.music_client: return
        if str(self.current_right_click_row) not in self.music_records: return
        
        song_info = self.music_records[str(self.current_right_click_row)]
        song_name = song_info.get('song_name', '未知歌曲')
        singers = ', '.join(song_info.get('singers', []))
        
        reply = QMessageBox.question(
            self, "确认下载", 
            f"确定要下载这首歌曲吗？\n\n{song_name} - {singers}\n\n保存目录：{self.save_dir}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes: return
        
        dlg = SimpleProgressDialog("下载中", f"正在下载：{song_name}", self.save_dir, self)
        dlg.show()
        self.download_thread = DownloadThread(self.music_client, [song_info])
        
        def on_finished():
            dlg.accept()
            QMessageBox.information(self, "完成", f"下载完成！\n\n{song_name} - {singers}\n\n文件保存在：{self.save_dir}")
        def on_error(error_msg):
            dlg.accept()
            QMessageBox.critical(self, "错误", f"下载失败：{error_msg}")
        
        self.download_thread.finished.connect(on_finished)
        self.download_thread.error.connect(on_error)
        self.download_thread.start()

    def select_all_songs(self):
        for row in range(self.results_table.rowCount()):
            try: self.results_table.cellWidget(row, 0).findChild(QCheckBox).setChecked(True)
            except: pass

    def deselect_all_songs(self):
        for row in range(self.results_table.rowCount()):
            try: self.results_table.cellWidget(row, 0).findChild(QCheckBox).setChecked(False)
            except: pass

    def on_browse_save_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.current_dir)
        if dir_path:
            self.save_dir = dir_path
            self.save_dir_edit.setText(dir_path)

    def init_music_client(self):
        if not MUSICDL_AVAILABLE: return None
        os.makedirs(self.save_dir, exist_ok=True)
        my_init_music_clients_cfg = {}
        src_names = []
        limit = self.spin_limit.value()
        for source in self.get_selected_sources():
            my_init_music_clients_cfg[source] = {'search_size_per_source': limit, 'work_dir': self.save_dir}
            src_names.append(source)
        if not src_names:
            QMessageBox.warning(self, "提示", "请至少选择一个音乐来源！")
            return None
        try:
            return musicdl.MusicClient(music_sources=src_names, init_music_clients_cfg=my_init_music_clients_cfg)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"初始化 musicdl 客户端失败：{str(e)}")
            return None

    def get_selected_sources(self):
        return [self.source_map_cn_to_en[cb.text()] for cb in self.source_checkboxes if cb.isChecked()]

    def get_file_format(self, song_info):
        format_fields = ['format', 'ext', 'file_format', 'type']
        for field in format_fields:
            if field in song_info and song_info[field]:
                return str(song_info[field]).upper()
        if 'download_url' in song_info and song_info['download_url']:
            url = song_info['download_url'].lower()
            if '.mp3' in url: return 'MP3'
            elif '.flac' in url: return 'FLAC'
            elif '.wav' in url: return 'WAV'
            elif '.m4a' in url: return 'M4A'
            elif '.aac' in url: return 'AAC'
        return '未知'

    def get_album_image_url(self, song_info):
        image_fields = ['cover', 'album_cover', 'pic', 'picture', 'img', 'image', 'album_img', 'album_pic', 'cover_url', 'pic_url']
        for field in image_fields:
            if field in song_info and song_info[field]:
                url = str(song_info[field])
                if url.startswith('http'): return url
        return ''

    def load_table_with_results(self, search_results):
        self.results_table.setRowCount(0)
        self.search_results = search_results
        self.music_records = {}
        self.image_threads = []
        
        # 收集所有歌曲
        all_songs = []
        for per_source_search_results in search_results.values():
            all_songs.extend(per_source_search_results)
        
        # 先加载表格（无论是否自动下载）
        self.results_table.setRowCount(len(all_songs))
        row = 0
        for _, (_, per_source_search_results) in enumerate(search_results.items()):
            for _, per_source_search_result in enumerate(per_source_search_results):
                w = QWidget()
                lay = QHBoxLayout(w)
                lay.addWidget(QCheckBox())
                lay.setAlignment(Qt.AlignCenter)
                lay.setContentsMargins(0, 0, 0, 0)
                self.results_table.setCellWidget(row, 0, w)
                
                try:
                    singers = per_source_search_result.get('singers', '')
                    song_name = per_source_search_result.get('song_name', '')
                    file_size = per_source_search_result.get('file_size', '')
                    duration = per_source_search_result.get('duration', '')
                    album = per_source_search_result.get('album', '')
                    source = per_source_search_result.get('source', '')
                    file_format = self.get_file_format(per_source_search_result)
                    album_image_url = self.get_album_image_url(per_source_search_result)
                    source_cn = self.source_map_en_to_cn.get(source, source)
                    
                    items = ['', str(song_name), str(singers), str(album), str(file_format), str(file_size), str(duration), str(source_cn)]
                    for column, item in enumerate(items):
                        if column == 0: continue
                        table_item = QTableWidgetItem(item)
                        table_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                        self.results_table.setItem(row, column + 1, table_item)
                    
                    self.music_records.update({str(row): per_source_search_result})
                    
                    if album_image_url:
                        image_thread = ImageDownloadThread(row, album_image_url)
                        image_thread.finished.connect(self.on_image_downloaded)
                        image_thread.error.connect(self.on_image_error)
                        image_thread.start()
                        self.image_threads.append(image_thread)
                except Exception as e:
                    print(f"处理第 {row} 行时出错: {e}")
                row += 1
        self.btn_download.setEnabled(row > 0)
        
        # 【修改】如果开启了自动下载，直接开始下载（不弹窗确认）
        if self.auto_download_after_search and all_songs:
            self.auto_download_all_songs(all_songs)
        else:
            QMessageBox.information(self, "完成", f"搜索完成！共找到 {row} 首歌曲\n专辑图片正在后台加载中...")

    # 自动下载所有歌曲（修改：不弹窗确认，直接下载，弹窗显示保存位置）
    def auto_download_all_songs(self, all_songs):
        if not all_songs or not self.music_client: return
        
        # 直接显示下载弹窗，显示保存位置
        dlg = SimpleProgressDialog("🚀 自动下载中", f"正在下载 {len(all_songs)} 首歌曲", self.save_dir, self)
        dlg.show()
        
        self.download_thread = DownloadThread(self.music_client, all_songs)
        
        def on_finished():
            dlg.accept()
            QMessageBox.information(self, "🎉 下载完成", f"成功下载 {len(all_songs)} 首歌曲！\n保存目录：{self.save_dir}")
        
        def on_error(error_msg):
            dlg.accept()
            QMessageBox.critical(self, "❌ 下载失败", f"批量下载失败：{error_msg}")
        
        self.download_thread.finished.connect(on_finished)
        self.download_thread.error.connect(on_error)
        self.download_thread.start()

    def on_image_downloaded(self, row, pixmap):
        try:
            label = QLabel()
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignCenter)
            self.results_table.setCellWidget(row, 1, label)
        except Exception as e:
            print(f"显示图片失败: {e}")

    def on_image_error(self, row):
        try:
            label = QLabel("🎵")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size: 24px; color: #ccc;")
            self.results_table.setCellWidget(row, 1, label)
        except Exception as e:
            print(f"显示占位符失败: {e}")

    def get_songs_by_download_scope(self):
        scope = self.combo_download_scope.currentText()
        songs_to_download = []
        for row in range(self.results_table.rowCount()):
            try:
                checkbox = self.results_table.cellWidget(row, 0).findChild(QCheckBox)
                is_checked = checkbox.isChecked()
                if (scope == "全选" or 
                    (scope == "勾选" and is_checked) or 
                    (scope == "未勾选" and not is_checked)):
                    if str(row) in self.music_records:
                        songs_to_download.append(self.music_records[str(row)])
            except Exception as e:
                print(f"获取下载列表时出错: {e}")
        return songs_to_download

    def on_search(self):
        keyword = self.search_edit.text().strip()
        if not keyword:
            QMessageBox.warning(self, "提示", "请输入搜索内容！")
            return
        self.music_client = self.init_music_client()
        if not self.music_client: return
        dlg = SimpleProgressDialog("搜索中", "正在搜索音乐，请稍候...", None, self)
        dlg.show()
        self.search_thread = SearchThread(self.music_client, keyword, self.search_mode.currentText())
        
        def on_finished(results):
            dlg.accept()
            self.load_table_with_results(results)
        def on_error(error_msg):
            dlg.accept()
            QMessageBox.critical(self, "错误", f"搜索失败：{error_msg}")
        
        self.search_thread.finished.connect(on_finished)
        self.search_thread.error.connect(on_error)
        self.search_thread.start()

    def count_downloaded_files(self):
        source_counts = {}
        for item in os.listdir(self.save_dir):
            item_path = os.path.join(self.save_dir, item)
            if os.path.isdir(item_path) and item in self.source_map_en_to_cn:
                file_count = 0
                for filename in os.listdir(item_path):
                    if os.path.isfile(os.path.join(item_path, filename)):
                        file_count += 1
                if file_count > 0:
                    source_counts[self.source_map_en_to_cn[item]] = {"path": item_path, "count": file_count}
        return source_counts

    def on_download(self):
        if not self.music_client:
            QMessageBox.warning(self, "提示", "请先搜索音乐！")
            return
        songs_to_download = self.get_songs_by_download_scope()
        if not songs_to_download:
            QMessageBox.warning(self, "提示", "没有符合条件的歌曲！")
            return
        reply = QMessageBox.question(
            self, "确认下载",
            f"确定要下载 {len(songs_to_download)} 首歌曲吗？\n保存目录：{self.save_dir}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes: return
        
        dlg = SimpleProgressDialog("下载中", f"正在下载 {len(songs_to_download)} 首歌曲", self.save_dir, self)
        dlg.show()
        self.download_thread = DownloadThread(self.music_client, songs_to_download)
        
        def on_finished():
            dlg.accept()
            source_counts = self.count_downloaded_files()
            total_downloaded = sum(info["count"] for info in source_counts.values())
            message = f"✅ 下载完成！\n\n📁 总保存目录：{self.save_dir}\n📊 本次共下载：{total_downloaded} 首歌曲\n\n📂 各音乐源下载详情：\n"
            for source_name, info in source_counts.items():
                message += f"  • {source_name}: {info['count']} 首\n    路径：{info['path']}\n"
            QMessageBox.information(self, "下载完成", message)
        def on_error(error_msg):
            dlg.accept()
            QMessageBox.critical(self, "错误", f"下载失败：{error_msg}")
        
        self.download_thread.finished.connect(on_finished)
        self.download_thread.error.connect(on_error)
        self.download_thread.start()

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    win = MusicDownloader()
    win.show()
    sys.exit(app.exec_())