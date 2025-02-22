# window.py
#
# Copyright 2022 knuxify
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE X CONSORTIUM BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# Except as contained in this notice, the name(s) of the above copyright
# holders shall not be used in advertising or otherwise to promote the sale,
# use or other dealings in this Software without prior written
# authorization.

from .common import is_valid_music_file, VALID_AUDIO_MIMES
from .dialogs import EartagCloseWarningDialog, EartagDiscardWarningDialog
from .fileview import EartagFileView # noqa: F401
from .filemanager import EartagFileManager
from .sidebar import EartagSidebar  # noqa: F401
from .rename import EartagRenameDialog
from .acoustid import EartagAcoustIDDialog

from gi.repository import Adw, Gdk, GLib, Gtk, GObject
import os
import magic
import mimetypes
import shutil

@Gtk.Template(resource_path='/app/drey/EarTag/ui/nofile.ui')
class EartagNoFile(Adw.Bin):
    __gtype_name__ = 'EartagNoFile'

    open_file = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

    def grab_button_focus(self, *args):
        self.open_file.grab_focus()

    @Gtk.Template.Callback()
    def on_add_file(self, *args):
        window = self.get_native()
        window.open_mode = EartagFileManager.LOAD_OVERWRITE
        window.show_file_chooser(folders=False)

    @Gtk.Template.Callback()
    def on_add_folder(self, *args):
        window = self.get_native()
        window.open_mode = EartagFileManager.LOAD_OVERWRITE
        window.show_file_chooser(folders=True)

@Gtk.Template(resource_path='/app/drey/EarTag/ui/window.ui')
class EartagWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'EartagWindow'

    save_button = Gtk.Template.Child()
    window_title = Gtk.Template.Child()
    container_stack = Gtk.Template.Child()
    container_flap = Gtk.Template.Child()

    sidebar = Gtk.Template.Child()
    sidebar_headerbar = Gtk.Template.Child()
    sidebar_search_button = Gtk.Template.Child()
    select_multiple_button = Gtk.Template.Child()
    sort_button = Gtk.Template.Child()

    no_file = Gtk.Template.Child()
    file_view = Gtk.Template.Child()

    no_file_widget = Gtk.Template.Child()

    toast_overlay = Gtk.Template.Child()
    overlay = Gtk.Template.Child()
    drop_highlight_revealer = Gtk.Template.Child()

    primary_menu_button = Gtk.Template.Child()
    empty_primary_menu_button = Gtk.Template.Child()

    force_close = False
    file_chooser = None

    open_mode = EartagFileManager.LOAD_OVERWRITE

    def __init__(self, application, paths=None):
        super().__init__(application=application, title='Ear Tag')

        self.audio_file_filter = Gtk.FileFilter()
        for mime in VALID_AUDIO_MIMES:
            self.audio_file_filter.add_mime_type(mime)

        self.file_manager = EartagFileManager(self)
        self.file_view.set_file_manager(self.file_manager)
        self.sidebar.set_file_manager(self.file_manager)
        self.file_manager.connect('notify::is-modified', self.toggle_save_button)
        self.file_manager.connect('notify::has-error', self.toggle_save_button)
        self.file_manager.files.connect('items-changed', self.toggle_fileview)
        self.file_manager.connect('refresh-needed', self.update_state)
        self.file_manager.connect('selection-changed', self.update_state)
        self.file_manager.load_task.connect('notify::progress', self.update_loading_progress)
        self.sidebar_search_button.bind_property(
            'active',
            self.sidebar.search_bar, 'search-mode-enabled',
            flags=GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.select_multiple_button.bind_property('active', self.sidebar, 'selection-mode',
            flags=GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.select_multiple_button.bind_property('active', self.sidebar.action_bar, 'revealed',
            flags=GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )

        self.connect('close-request', self.on_close_request)

        self.drop_target = Gtk.DropTarget(
            actions=Gdk.DragAction.COPY,
            formats=Gdk.ContentFormats.new_for_gtype(Gdk.FileList)
            )
        self.drop_target.connect('accept', self.on_drag_accept)
        self.drop_target.connect('enter', self.on_drag_hover)
        self.drop_target.connect('leave', self.on_drag_unhover)
        self.drop_target.connect('drop', self.on_drag_drop)
        self.add_controller(self.drop_target)

        self.toggle_fileview()

        self.connect('realize', self._late_init)

        if paths:
            self.file_manager.load_files(paths, mode=EartagFileManager.LOAD_OVERWRITE)

    def _late_init(self, *args):
        self.file_view.setup_resize_handler()

    def update_loading_progress(self, task, *args):
        loading_progress = task.progress
        is_loading = loading_progress != 0
        self.sidebar_headerbar.set_sensitive(not is_loading)
        if self.file_manager.files.get_n_items() == 0 and is_loading:
            self.container_stack.set_visible_child(self.container_flap)

    def update_state(self, *args):
        # Set up the active view (hide fileview if there are no selected files)
        selected_files_count = len(self.file_manager.selected_files)
        if selected_files_count <= 0:
            self.get_application().save_cover_action.set_enabled(False)
            self.get_application().rename_action.set_enabled(False)
            self.get_application().identify_action.set_enabled(False)
            self.set_title('Ear Tag')
            self.window_title.set_subtitle('')
            if self.file_manager.files:
                self.file_view.content_stack.set_visible_child(self.file_view.select_file)

            self.run_sort()
            return False
        else:
            files = self.file_manager.selected_files

        self.file_view.content_stack.set_visible_child(self.file_view.content_scroll)

        # Set up window title and file info label
        if len(files) == 1:
            file = files[0]
            file_basename = os.path.basename(file.path)
            self.set_title('{f} — Ear Tag'.format(f=file_basename))
            self.window_title.set_subtitle(file_basename)
            self.get_application().save_cover_action.set_enabled(True)
        else:
            # TRANSLATOR: Placeholder for file path when multiple files are selected
            _multiple_files = _('(Multiple files selected)')
            self.set_title('{f} — Ear Tag'.format(f=_multiple_files))
            self.window_title.set_subtitle(_multiple_files)
            self.get_application().save_cover_action.set_enabled(False)

        self.get_application().rename_action.set_enabled(True)
        self.get_application().identify_action.set_enabled(True)

        self.toggle_save_button()

        self.file_view.update_binds()

    def toggle_fileview(self, *args):
        """
        Shows/hides the fileview/"no files" message depending on opened files.
        """
        if self.file_manager.files.get_n_items() > 0:
            self.container_stack.set_visible_child(self.container_flap)
            self.sidebar_headerbar.set_sensitive(self.file_manager.load_task.progress in (0, 1))
        else:
            self.container_stack.set_visible_child(self.no_file)
            self.no_file_widget.grab_button_focus()
            self.sidebar_headerbar.set_sensitive(False)
            if self.sidebar.selection_mode:
                self.select_multiple_button.set_active(False)
        self.sidebar.toggle_fileview()

    def on_drag_accept(self, target, drop, *args):
        drop.read_value_async(Gdk.FileList, 0, None, self.verify_files_valid)
        return True

    def verify_files_valid(self, drop, task, *args):
        try:
            files = drop.read_value_finish(task).get_files()
        except GLib.GError:
            self.drop_target.reject()
            self.on_drag_unhover()
            return False
        for file in files:
            path = file.get_path()
            if not is_valid_music_file(path):
                self.drop_target.reject()
                self.on_drag_unhover()

    def on_drag_hover(self, *args):
        self.drop_highlight_revealer.set_reveal_child(True)
        self.drop_highlight_revealer.set_can_target(True)
        return Gdk.DragAction.COPY

    def on_drag_unhover(self, *args):
        self.drop_highlight_revealer.set_reveal_child(False)
        self.drop_highlight_revealer.set_can_target(False)

    def on_drag_drop(self, drop_target, value, *args):
        files = value.get_files()
        paths = []
        for file in files:
            paths.append(file.get_path())
        self.open_mode = EartagFileManager.LOAD_INSERT
        self.open_files(paths)
        self.open_mode = EartagFileManager.LOAD_OVERWRITE
        self.on_drag_unhover()

    def show_file_chooser(self, folders=False):
        """Shows the file chooser."""
        if self.file_chooser:
            return

        if folders:
            action = Gtk.FileChooserAction.SELECT_FOLDER
            filter = None
            title = _("Open Folder")
        else:
            action = Gtk.FileChooserAction.OPEN
            filter = self.audio_file_filter
            title = _("Open File")

        self.file_chooser = Gtk.FileChooserNative(
                                title=title,
                                transient_for=self,
                                action=action,
                                select_multiple=True
                                )

        if filter:
            self.file_chooser.set_filter(filter)

        self.file_chooser.connect('response', self.open_file_from_dialog)
        self.file_chooser.show()

    def open_files(self, paths):
        """
        Loads the files with the given paths. Note that this does not perform
        any validation; caller functions are meant to check for this manually.
        """
        if self.open_mode != EartagFileManager.LOAD_INSERT and self.file_manager._is_modified:
            self.discard_warning = EartagDiscardWarningDialog(self, paths)
            self.discard_warning.show()
            return False

        self.file_manager.load_files(paths, mode=self.open_mode)

    def open_file_from_dialog(self, dialog, response):
        """
        Callback for a FileChooser that takes the response and opens the file
        selected in the dialog.
        """
        self.file_chooser.destroy()
        self.file_chooser = None
        if response == Gtk.ResponseType.ACCEPT:
            paths = []
            for file in list(dialog.get_files()):
                _path = file.get_path()
                if os.path.isdir(_path):
                    for _file in os.listdir(_path):
                        _fpath = os.path.join(_path, _file)
                        if os.path.isfile(_fpath) and is_valid_music_file(_fpath):
                            paths.append(_fpath)
                else:
                    paths.append(_path)
            if not paths:
                toast = Adw.Toast.new(_("No supported files found in opened folder"))
                self.toast_overlay.add_toast(toast)
                return
            return self.open_files(paths)

    def toggle_save_button(self, *args):
        if self.file_manager.has_error:
            self.save_button.set_tooltip_text(_("Some of the opened files have invalid values; cannot save")) # noqa: E501
        else:
            self.save_button.set_tooltip_text('')
        self.save_button.set_sensitive(
                self.file_manager.is_modified and not self.file_manager.has_error
        )

    @Gtk.Template.Callback()
    def show_sidebar(self, *args):
        self.container_flap.set_reveal_flap(True)
        self.sidebar.file_list.grab_focus()

    @Gtk.Template.Callback()
    def hide_sidebar(self, *args):
        self.container_flap.set_reveal_flap(False)

    @Gtk.Template.Callback()
    def run_sort(self, *args):
        if self.file_manager.files:
            self.sidebar.file_list.sorter.changed(Gtk.SorterChange.DIFFERENT)

    @Gtk.Template.Callback()
    def on_save(self, *args):
        if not self.file_manager.save():
            return False

    @Gtk.Template.Callback()
    def insert_file(self, *args):
        self.open_mode = EartagFileManager.LOAD_INSERT
        self.show_file_chooser()

    def on_close_request(self, *args):
        if not self.force_close and list(self.file_manager.files) and \
                self.file_manager._is_modified:
            self.close_request_dialog = EartagCloseWarningDialog(self)
            self.close_request_dialog.present()
            return True

    def show_rename_dialog(self, *args):
        self.rename_dialog = EartagRenameDialog(self)
        self.rename_dialog.present()

    def show_acoustid_dialog(self, *args):
        self.acoustid_dialog = EartagAcoustIDDialog(self)
        self.acoustid_dialog.present()

    def save_cover(self, *args):
        """Opens a file dialog to have the cover art to a file."""
        self.file_chooser = Gtk.FileChooserNative(
                                title=_("Save Album Cover To…"),
                                transient_for=self.get_native(),
                                action=Gtk.FileChooserAction.SAVE
                                )

        self.file_chooser.connect('response', self._save_cover_response)
        self.file_chooser.show()

    def _save_cover_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            cover_path = self.file_manager.selected_files[0].cover_path
            if cover_path:
                save_path = dialog.get_file().get_path()
                cover_mime = magic.from_file(cover_path, mime=True)
                cover_extension = mimetypes.guess_extension(cover_mime)
                if cover_extension and not save_path.endswith(cover_extension):
                    save_path += cover_extension
                shutil.copyfile(cover_path, save_path)
        dialog.destroy()
