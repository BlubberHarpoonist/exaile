# Copyright (C) 2010 Aren Olson
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
#
# The developers of the Exaile media player hereby grant permission
# for non-GPL compatible GStreamer and Exaile plugins to be used and
# distributed together with GStreamer and Exaile. This permission is
# above and beyond the permissions granted by the GPL license by which
# Exaile is covered. If you modify this code, you may extend this
# exception to your version of the code, but you are not obligated to
# do so. If you do not wish to do so, delete this exception statement
# from your version.


import collections
import os
import random
import re

import glib, gobject, gtk, pango

from xl.nls import gettext as _

from xl import (common, event, player, providers, settings, trax, xdg)
from xl.playlist import Playlist, PlaylistManager
from xlgui import guiutil, icons
import playlist_columns
from xl.common import MetadataList
from xlgui.widgets.notebook import SmartNotebook, NotebookPage, NotebookTab
from xlgui.widgets import menu

import logging
logger = logging.getLogger(__name__)


class PlaylistNotebook(SmartNotebook):
    def __init__(self, manager_name):
        SmartNotebook.__init__(self)
        self.tab_manager = PlaylistManager(manager_name)
        self.load_saved_tabs()

    def create_tab_from_playlist(self, playlist):
        """
            Create a tab that will contain the passed-in playlist

            :param playlist: The playlist to create tab from
            :type playlist: :class:`xl.playlist.Playlist`
        """
        page = PlaylistPage(playlist)
        tab = NotebookTab(self, page)
        self.add_tab(tab, page)
        return tab

    def create_new_playlist(self):
        """
            Create a new tab containing a blank playlist. The tab will
            be automatically given a unique name.
        """
        seen = []

        for n in range(self.get_n_pages()):
            page = self.get_nth_page(n)
            name = page.get_name()
            if name.startswith('Playlist '):
                try:
                    val = int(name[9:])
                except:
                    pass
                else:
                    seen.append(val)
        n = 1

        while True:
            if n not in seen:
                break
            n += 1

        pl = Playlist("Playlist %d"%n)

        return self.create_tab_from_playlist(pl)

    def add_default_tab(self):
        return self.create_new_playlist()

    def load_saved_tabs(self):
        names = self.tab_manager.list_playlists()
        if not names:
            self.add_default_tab()
            return

        count = -1
        count2 = 0
        names.sort()
        # holds the order#'s of the already added tabs
        added_tabs = {}
        name_re = re.compile(
                r'^order(?P<tab>\d+)\.(?P<tag>[^.]*)\.(?P<name>.*)$')
        for i, name in enumerate(names):
            match = name_re.match(name)
            if not match or not match.group('tab') or not match.group('name'):
                logger.error("%s did not match valid playlist file"
                        % repr(name))
                continue

            logger.debug("Adding playlist %d: %s" % (i, name))
            logger.debug("Tab:%s; Tag:%s; Name:%s" % (match.group('tab'),
                                                     match.group('tag'),
                                                     match.group('name'),
                                                     ))
            pl = self.tab_manager.get_playlist(name)
            pl.name = match.group('name')

            if match.group('tab') not in added_tabs:
                self.create_tab_from_playlist(pl)
                added_tabs[match.group('tab')] = pl
            pl = added_tabs[match.group('tab')]

            if match.group('tag') == 'current':
                count = i
                if player.QUEUE.current_playlist is None:
                    player.QUEUE.set_current_playlist(pl)
            elif match.group('tag') == 'playing':
                count2 = i
                player.QUEUE.set_current_playlist(pl)

        # If there's no selected playlist saved, use the currently
        # playing
        if count == -1:
            count = count2

        self.set_current_page(count)

    def save_current_tabs(self):
        """
            Saves the open tabs
        """
        # first, delete the current tabs
        names = self.tab_manager.list_playlists()
        for name in names:
            logger.debug("Removing tab %s" % name)
            self.tab_manager.remove_playlist(name)

        for i in range(self.get_n_pages()):
            pl = self.get_nth_page(i).playlist
            tag = ''
            if pl is player.QUEUE.current_playlist:
                tag = 'playing'
            elif i == self.get_current_page():
                tag = 'current'
            pl.name = "order%d.%s.%s" % (i, tag, pl.name)
            logger.debug("Saving tab %d: %s" % (i, pl.name))

            try:
                self.tab_manager.save_playlist(pl, True)
            except:
                # an exception here could cause exaile to be unable to quit.
                # Catch all exceptions.
                import traceback
                traceback.print_exc()


# do this in a function to avoid polluting the global namespace
def __create_playlist_tab_context_menu():
    smi = menu.simple_menu_item
    sep = menu.simple_separator
    items = []
    items.append(smi('new-tab', [], _("New Playlist"), 'tab-new',
        lambda w, n, o, c: o.tab.notebook.create_new_playlist()))
    items.append(sep('new-tab-sep', ['new-tab']))
    items.append(smi('rename', ['new-tab-sep'], _("Rename"), 'gtk-edit',
        lambda w, n, o, c: o.tab.start_rename()))
    items.append(smi('clear', ['rename'], _("Clear"), 'gtk-clear',
        lambda w, n, o, c: o.playlist.clear()))
    items.append(sep('tab-close-sep', ['clear']))
    items.append(smi('tab-close', ['tab-close-sep'], _("Close"), 'gtk-close',
        lambda w, n, o, c: o.tab.close()))
    for item in items:
        providers.register('playlist-tab-context', item)
__create_playlist_tab_context_menu()


class PlaylistContextMenu(menu.ProviderMenu):
    def __init__(self, page):
        """
            :param page: The :class:`PlaylistPage` this menu is
                associated with.
        """
        menu.ProviderMenu.__init__(self, 'playlist-context', page)

    def get_parent_context(self):
        context = {}
        context['selected-tracks'] = self._parent.get_selected_items()

        return context

def __create_playlist_context_menu():
    smi = menu.simple_menu_item
    sep = menu.simple_separator
    items = []
    items.append(smi('append-queue', [], _("Append to Queue"), 'gtk-add',
            lambda w, n, o, c: player.QUEUE.add_tracks(
            [t[1] for t in c['selected-tracks']])))
    def toggle_spat_cb(widget, name, playlistpage, context):
        position = context['selected-tracks'][0][0]
        if position != playlistpage.playlist.spat_position:
            playlistpage.playlist.spat_position = position
        else:
            playlistpage.playlist.spat_position = -1
    items.append(smi('toggle-spat', ['append-queue'],
            _("Toggle Stop After This Track"), 'gtk-stop', toggle_spat_cb))
    items.append(menu.RatingMenuItem('rating', ['toggle-spat']))
    # TODO: custom playlist item here
    items.append(sep('sep1', ['rating']))
    def remove_tracks_cb(widget, name, playlistpage, context):
        tracks = context['selected-tracks']
        playlist = playlistpage.playlist
        # If it's all one block, just delete it in one chunk for
        # maximum speed.
        positions = [t[0] for t in tracks]
        if positions == range(positions[0], positions[0]+len(positions)):
            del playlist[positions[0]:positions[0]+len(positions)+1]
        else:
            for position, track in tracks[::-1]:
                del playlist[position]
    items.append(smi('remove', ['sep1'], _("Remove"), 'gtk-remove',
        remove_tracks_cb))
    items.append(sep('sep2', ['remove']))
    items.append(smi('properties', ['sep2'], _("Properties"), 'gtk-properties',
        lambda w, n, o, c: False))
    for item in items:
        providers.register('playlist-context', item)
__create_playlist_context_menu()


class PlaylistPage(gtk.VBox, NotebookPage):
    """
        Displays a playlist and associated controls.
    """
    menu_provider_name = 'playlist-tab-context'
    def __init__(self, playlist):
        """
            :param playlist: The :class:`xl.playlist.Playlist` to display
                in this page.
        """
        gtk.VBox.__init__(self)
        NotebookPage.__init__(self)

        self.playlist = playlist
        self.icon = None

        uifile = xdg.get_data_path("ui", "playlist.ui")
        self.builder = gtk.Builder()
        self.builder.add_from_file(uifile)
        plpage = self.builder.get_object("playlist_page")
        for child in plpage.get_children():
            plpage.remove(child)

        self.shuffle_button = self.builder.get_object("shuffle_button")
        self.repeat_button = self.builder.get_object("repeat_button")
        self.dynamic_button = self.builder.get_object("dynamic_button")
        self.search_entry = guiutil.SearchEntry(
                self.builder.get_object("search_entry"))

        self.builder.connect_signals(self)

        self.plwin = self.builder.get_object("playlist_window")
        self.controls = self.builder.get_object("controls_box")
        self.pack_start(self.plwin, True, True, padding=2)
        self.pack_start(self.controls, False, False, padding=2)

        self.view = PlaylistView(playlist)
        self.plwin.add(self.view)
        self._filter_string = ""
        self.modelfilter = self.view.model.filter_new()
        self.modelfilter.set_visible_func(self.model_visible_func)
        self.view.set_model(self.modelfilter)

        event.add_callback(self.on_shuffle_mode_changed,
                "playlist_shuffle_mode_changed", self.playlist)
        event.add_callback(self.on_repeat_mode_changed,
                "playlist_repeat_mode_changed", self.playlist)
        self.view.model.connect('row-changed', self.on_row_changed)

        self.show_all()

    ## NotebookPage API ##

    def get_name(self):
        return self.playlist.name

    def set_name(self, name):
        self.playlist.name = name

    def handle_close(self):
        return True

    ## End NotebookPage ##

    def on_shuffle_button_press_event(self, widget, event):
        self.__show_toggle_menu(Playlist.shuffle_modes,
                Playlist.shuffle_mode_names, self.on_shuffle_mode_set,
                'shuffle_mode', widget, event)

    def on_repeat_button_press_event(self, widget, event):
        self.__show_toggle_menu(Playlist.repeat_modes,
                Playlist.repeat_mode_names, self.on_repeat_mode_set,
                'repeat_mode', widget, event)

    def on_dynamic_button_toggled(self, widget):
        if widget.get_active():
            self.playlist.dynamic_mode = self.playlist.dynamic_modes[1]
        else:
            self.playlist.dynamic_mode = self.playlist.dynamic_modes[0]

    def on_search_entry_activate(self, entry):
        self._filter_string = entry.get_text()
        self.modelfilter.refilter()

    def __show_toggle_menu(self, names, display_names, callback, attr,
            widget, event):
        """
            Display the menu on the shuffle/repeat toggle buttons

            :param names: The list of names of the menu entries
            :param display_names: The list of names to display on
                each menu entry.
            :param callback: The function to call when a menu item is
                activated. It will be passed the name of the activated item.
            :param attr: The attribute of self.playlist to look at to
                determine the currently-selected item.
            :param widget: The ToggleButton to display the menu on
            :param event: The gtk event that triggered the menu display
        """
        widget.set_active(True)
        menu = gtk.Menu()
        menu.connect('deactivate', self._mode_menu_set_toggle, widget, attr)
        prev = None
        mode = getattr(self.playlist, attr)
        for name, disp in zip(names, display_names):
            item = gtk.RadioMenuItem(prev, disp)
            if name == mode:
                item.set_active(True)
            item.connect('activate', callback, name)
            menu.append(item)
            if prev is None:
                menu.append(gtk.SeparatorMenuItem())
            prev = item
        menu.show_all()
        menu.popup(None, None, self._mode_menu_set_pos,
                event.button, event.time, widget)
        menu.reposition()

    def _mode_menu_set_pos(self, menu, button):
        """
            Nicely position the shuffle/repeat popup menu with the
            button's corner.
        """
        window_x, window_y = self.window.get_position()
        button_allocation = button.get_allocation()
        menu_allocation = menu.get_allocation()
        position = (
            window_x + button_allocation.x + 1,
            window_y + button_allocation.y - menu_allocation.height - 1
        )

        return (position[0], position[1], True)

    def _mode_menu_set_toggle(self, menu, button, name):
        mode = getattr(self.playlist, name)
        if mode == 'disabled':
            button.set_active(False)
        else:
            button.set_active(True)

    def on_shuffle_mode_set(self, widget, mode):
        """
            Callback for the Shuffle mode menu
        """
        self.playlist.shuffle_mode = mode

    def on_shuffle_mode_changed(self, evtype, playlist, mode):
        """
            Updates the UI to reflect changes in the shuffle mode
        """
        if mode == 'disabled':
            self.shuffle_button.set_active(False)
        else:
            self.shuffle_button.set_active(True)

    def on_repeat_mode_set(self, widget, mode):
        """
            Callback for the Repeat mode menu
        """
        self.playlist.repeat_mode = mode

    def on_repeat_mode_changed(self, evtype, playlist, mode):
        """
            Updates the UI to reflect changes in the repeat mode
        """
        if mode == 'disabled':
            self.repeat_button.set_active(False)
        else:
            self.repeat_button.set_active(True)

    def on_row_changed(self, model, path, iter):
        """
            Sets the tab icon to reflect the playback status
        """
        if path[0] == self.playlist.current_position:
            pixbuf = model.get_value(iter, 1)
            if pixbuf == model.clear_pixbuf:
                pixbuf = None
            self.tab.set_icon(pixbuf)

    def model_visible_func(self, model, iter):
        if self._filter_string == "":
            return True
        return trax.match_track_from_string(
                model.get_value(iter, 0), self._filter_string,
                case_sensitive=False, keyword_tags=['artist', 'title', 'album'])
                # FIXME: use currently-visible columns + base
                # tags for filter



class PlaylistView(gtk.TreeView):
    default_columns = ['tracknumber', 'title', 'album', 'artist', '__length']
    base_sort_tags = ['artist', 'date', 'album', 'discnumber',
            'tracknumber', 'title']
    def __init__(self, playlist):
        gtk.TreeView.__init__(self)
        self.playlist = playlist
        self.model = PlaylistModel(playlist, self.default_columns)
        self.menu = PlaylistContextMenu(self)
        self.dragging = False
        self.button_held = False    # used by columns to determine whether
                                    # a notify::width event was initiated
                                    # by the user.

        self.set_fixed_height_mode(True) # MASSIVE speedup - don't disable this!
        self.set_rules_hint(True)
        self.set_enable_search(True)
        self.selection = self.get_selection()
        self.selection.set_mode(gtk.SELECTION_MULTIPLE)

        self.set_model(self.model)
        self.columns_changed_id = 0
        self._setup_columns()

        self.targets = [("exaile-index-list", gtk.TARGET_SAME_WIDGET, 0),
                ("text/uri-list", 0, 0)]
        self.drag_source_set(gtk.gdk.BUTTON1_MASK, self.targets,
                gtk.gdk.ACTION_COPY|gtk.gdk.ACTION_MOVE)
        self.drag_dest_set(gtk.DEST_DEFAULT_ALL, self.targets,
                gtk.gdk.ACTION_COPY|gtk.gdk.ACTION_DEFAULT|
                gtk.gdk.ACTION_MOVE)

        event.add_callback(self.on_option_set, "gui_option_set")
        self.connect("row-activated", self.on_row_activated)
        self.connect("button-press-event", self.on_button_press)
        self.connect("button-release-event", self.on_button_release)

        self.connect("drag-begin", self.on_drag_begin)
        self.connect("drag-drop", self.on_drag_drop)
        self.connect("drag-data-get", self.on_drag_data_get)
        self.connect("drag-data-received", self.on_drag_data_received)
        self.connect("drag-data-delete", self.on_drag_data_delete)
        self.connect("drag-end", self.on_drag_end)
        self.connect("drag-motion", self.on_drag_motion)

    def set_cell_weight(self, cell, iter):
        """
            Called by columns in playlist_columns to set a CellRendererText's
            weight property for the playing track.
        """
        model = self.get_model()
        path = model.get_path(iter)
        track = model.get_value(iter, 0)
        if track == player.PLAYER.current and \
                path[0] == self.playlist.get_current_position() and \
                self.playlist == player.QUEUE.current_playlist:
            weight = pango.WEIGHT_HEAVY
        else:
            weight = pango.WEIGHT_NORMAL
        cell.set_property('weight', weight)

    def get_selected_tracks(self):
        """
            Returns a list of :class:`xl.trax.Track`
            which are currently selected in the playlist.
        """
        return [x[1] for x in self.get_selected_items()]

    def get_selected_paths(self):
        """
            Returns a list of pairs of treepaths
            which are currently selected in the playlist.
        """
        selection = self.get_selection()
        model, paths = selection.get_selected_rows()
        return paths

    def get_selected_items(self):
        """
            Returns a list of pairs of indices and :class:`xl.trax.Track`
            which are currently selected in the playlist.
        """
        paths = self.get_selected_paths()
        model = self.get_model()
        tracks = [(path[0], model.get_value(model.get_iter(path), 0)) for path in paths]
        return tracks

    def _refresh_columns(self):
        selection = self.get_selection()
        info = selection.get_selected_rows()
        # grab the first visible raw of the treeview
        firstpath = self.get_path_at_pos(4,4)
        topindex = None
        if firstpath:
            topindex = firstpath[0][0]

        self.disconnect(self.columns_changed_id)
        columns = self.get_columns()
        for col in columns:
            self.remove_column(col)

        self._setup_columns()
        self.columns_changed_id = self.connect("columns-changed",
                self.on_columns_changed)
        self.queue_draw()

        if firstpath:
            self.scroll_to_cell(topindex)
        if info:
            for path in info[1]:
                selection.select_path(path)

    def _setup_columns(self):
        col_ids = settings.get_option("gui/columns", self.default_columns)
        col_ids = [col for col in col_ids if col in playlist_columns.COLUMNS]
        if not col_ids:
            col_ids = self.default_columns
        self.model.columns = col_ids

        for position, column in enumerate(col_ids):
            position += 2 # offset for pixbuf column
            playlist_column = playlist_columns.COLUMNS[column](self, position)
            playlist_column.connect('clicked', self.on_column_clicked)
            self.append_column(playlist_column)
            header = playlist_column.get_widget()
            header.show()
            header.get_ancestor(gtk.Button).connect('button-press-event', self.on_header_button_press)

    def on_header_button_press(self, widget, event):
        if event.button == 3:
            m = menu.ProviderMenu('playlist-columns-menu', self)
            m.popup(None, None, None, event.button, event.time)
            return True

    def on_columns_changed(self, widget):
        columns = [c.id for c in self.get_columns()]
        if columns != settings.get_option('gui/columns', []):
            settings.set_option('gui/columns', columns)

    def on_column_clicked(self, column):
        order = None
        for col in self.get_columns():
            if col.id == column.id:
                order = column.get_sort_order()
                if order == gtk.SORT_ASCENDING:
                    order = gtk.SORT_DESCENDING
                else:
                    order = gtk.SORT_ASCENDING
                col.set_sort_indicator(True)
                col.set_sort_order(order)
            else:
                col.set_sort_indicator(False)
                col.set_sort_order(gtk.SORT_DESCENDING)
        reverse = order == gtk.SORT_DESCENDING
        self.playlist.sort([column.id] + self.base_sort_tags, reverse=reverse)

    def on_option_set(self, typ, obj, data):
        if data == "gui/columns":
            glib.idle_add(self._refresh_columns, priority=glib.PRIORITY_DEFAULT)

    def on_row_activated(self, *args):
        try:
            position, track = self.get_selected_items()[0]
        except IndexError:
            return

        self.playlist.set_current_position(position)
        player.QUEUE.play(track=track)
        player.QUEUE.set_current_playlist(self.playlist)

    def on_button_press(self, widget, event):
        self.button_held = True
        if event.button == 3:
            self.menu.popup(None, None, None, event.button, event.time)
            return True
        elif event.button == 1:
            selection = self.get_selection()
            path = self.get_path_at_pos(int(event.x), int(event.y))
            if path:
                if selection.count_selected_rows() <= 1:
                    return False
                else:
                    if selection.path_is_selected(path[0]):
                        if event.state & (gtk.gdk.SHIFT_MASK|gtk.gdk.CONTROL_MASK):
                            selection.unselect_path(path[0])
                        return True
                    elif not event.state & (gtk.gdk.SHIFT_MASK|gtk.gdk.CONTROL_MASK):
                        return True
                    return False
                if not selection.count_selected_rows():
                    selection.select_path(path[0])
        return False

    def on_button_release(self, widget, event):
        self.button_held = False
        if event.button != 1 or self.dragging:
            self.dragging = False
            return True

        if event.state & (gtk.gdk.SHIFT_MASK|gtk.gdk.CONTROL_MASK):
            return True

        selection = self.get_selection()
        selection.unselect_all()

        path = self.get_path_at_pos(int(event.x), int(event.y))
        if path:
            selection.select_path(path[0])

        return False

    ### DND handlers ###
    ## Source
    def on_drag_begin(self, widget, context):
        # TODO: set drag icon
        self.dragging = True

    def on_drag_data_get(self, widget, context, selection, info, etime):
        if selection.target == "exaile-index-list":
            positions = self.get_selected_paths()
            s = ",".join(str(i[0]) for i in positions)
            selection.set(selection.target, 8, s)
        elif selection.target == "text/uri-list":
            tracks = self.get_selected_tracks()
            uris = trax.util.get_uris_from_tracks(tracks)
            selection.set_uris(uris)

    def on_drag_data_delete(self, widget, context):
        self.stop_emission('drag-data-delete')

    def on_drag_end(self, widget, context):
        self.dragging = False

    ## Dest
    def on_drag_drop(self, widget, context, x, y, etime):
        return True

    def on_drag_data_received(self, widget, context, x, y, selection,
            info, etime):
        # stop default handler from running
        self.stop_emission('drag-data-received')
        drop_info = self.get_dest_row_at_pos(x, y)
        if drop_info:
            path, position = drop_info
            insert_position = path[0]
            if position in (gtk.TREE_VIEW_DROP_AFTER, gtk.TREE_VIEW_DROP_INTO_OR_AFTER):
                insert_position += 1
        else:
            insert_position = -1
        if selection.target == "exaile-index-list":
            positions = [int(x) for x in selection.data.split(",")]
            tracks = MetadataList()
            # TODO: this can probably be made more-efficient
            for i in positions:
                tracks.extend(self.playlist[i:i+1])
            if insert_position >= 0:
                self.playlist[insert_position:insert_position] = tracks
                for i, position in enumerate(positions[:]):
                    if position >= insert_position:
                        position += len(tracks)
                        positions[i] = position
            else:
                self.playlist.extend(tracks)
            for i in positions[::-1]:
                del self.playlist[i]
        elif selection.target == "text/uri-list":
            uris = selection.get_uris()
            tracks = []
            for u in uris:
                tracks.extend(trax.get_tracks_from_uri(u))
            if insert_position >= 0:
                self.playlist[insert_position:insert_position] = tracks
            else:
                self.playlist.extend(tracks)
        context.finish(True, False, etime)

    def on_drag_motion(self, widget, context, x, y, etime):
        info = self.get_dest_row_at_pos(x, y)

        if not info:
            return False

        path, position = info

        if position == gtk.TREE_VIEW_DROP_INTO_OR_BEFORE:
            position = gtk.TREE_VIEW_DROP_BEFORE
        elif position == gtk.TREE_VIEW_DROP_INTO_OR_AFTER:
            position = gtk.TREE_VIEW_DROP_AFTER

        self.set_drag_dest_row(path, position)

        return True

class PlaylistModel(gtk.GenericTreeModel):
    def __init__(self, playlist, columns):
        gtk.GenericTreeModel.__init__(self)
        self.playlist = playlist
        self.columns = columns

        event.add_callback(self.on_tracks_added,
                "playlist_tracks_added", playlist)
        event.add_callback(self.on_tracks_removed,
                "playlist_tracks_removed", playlist)
        event.add_callback(self.on_current_position_changed,
                "playlist_current_position_changed", playlist)
        event.add_callback(self.on_current_position_changed,
                "playlist_spat_position_changed", playlist)
        event.add_callback(self.on_playback_state_change,
                "playback_track_start")
        event.add_callback(self.on_playback_state_change,
                "playback_track_end")
        event.add_callback(self.on_playback_state_change,
                "playback_player_pause")
        event.add_callback(self.on_playback_state_change,
                "playback_player_resume")

        self.play_pixbuf = icons.ExtendedPixbuf(
                icons.MANAGER.pixbuf_from_stock(gtk.STOCK_MEDIA_PLAY))
        self.pause_pixbuf = icons.ExtendedPixbuf(
                icons.MANAGER.pixbuf_from_stock(gtk.STOCK_MEDIA_PAUSE))
        self.stop_pixbuf = icons.ExtendedPixbuf(
                icons.MANAGER.pixbuf_from_stock(gtk.STOCK_STOP))
        stop_overlay_pixbuf = self.stop_pixbuf.scale_simple(
                dest_width=self.stop_pixbuf.get_width() / 2,
                dest_height=self.stop_pixbuf.get_height() / 2,
                interp_type=gtk.gdk.INTERP_BILINEAR)
        stop_overlay_pixbuf = stop_overlay_pixbuf.move(
                offset_x=stop_overlay_pixbuf.get_width(),
                offset_y=stop_overlay_pixbuf.get_height(),
                resize=True)
        self.play_stop_pixbuf = self.play_pixbuf & stop_overlay_pixbuf
        self.pause_stop_pixbuf = self.pause_pixbuf & stop_overlay_pixbuf
        self.clear_pixbuf = self.play_pixbuf.copy()
        self.clear_pixbuf.fill(0x00000000)

    ### API for GenericTreeModel ###

    def on_get_flags(self):
        return gtk.TREE_MODEL_LIST_ONLY

    def on_get_n_columns(self):
        return len(self.columns)+1

    def on_get_column_type(self, index):
        if index == 0:
            return object
        elif index == 1:
            return gtk.gdk.Pixbuf
        else:
            return playlist_columns.COLUMNS[self.columns[index-2]].datatype

    def on_get_iter(self, path):
        rowref = path[0]
        if rowref < len(self.playlist):
            return rowref
        else:
            return None

    def on_get_path(self, rowref):
        return (rowref,)

    def on_get_value(self, rowref, column):
        if column == 0:
            return self.playlist[rowref]
        elif column == 1:
            if self.playlist.current_position == rowref and \
                    self.playlist[rowref] == player.PLAYER.current and \
                    self.playlist == player.QUEUE.current_playlist:
                state = player.PLAYER.get_state()
                spat = self.playlist.spat_position == rowref
                if state == 'playing':
                    if spat:
                        return self.play_stop_pixbuf
                    else:
                        return self.play_pixbuf
                elif state == 'paused':
                    if spat:
                        return self.pause_stop_pixbuf
                    else:
                        return self.pause_pixbuf
            if self.playlist.spat_position == rowref:
                return self.stop_pixbuf
            return self.clear_pixbuf
        else:
            tagname = self.columns[column-2]
            track = self.playlist[rowref]
            formatter = playlist_columns.FORMATTERS[tagname]
            return formatter.format(track)

    def on_iter_next(self, rowref):
        rowref = rowref+1
        if rowref < len(self.playlist):
            return rowref
        else:
            return None

    def on_iter_children(self, parent):
        return None

    def on_iter_has_child(self, rowref):
        return False

    def on_iter_n_children(self, rowref):
        if rowref:
            return 0
        return len(self.playlist)

    def on_iter_nth_child(self, parent, n):
        if parent:
            return None
        try:
            t = self.playlist[n]
            return n
        except IndexError:
            return None

    def on_iter_parent(self, child):
        return None


    ### Event callbacks to keep the model in sync with the playlist ###

    def on_tracks_added(self, event_type, playlist, tracks):
        for position, track in tracks:
            self.row_inserted((position,), self.get_iter((position,)))

    def on_tracks_removed(self, event_type, playlist, tracks):
        tracks.reverse()
        for position, track in tracks:
            self.row_deleted((position,))

    def on_current_position_changed(self, event_type, playlist, positions):
        for position in positions:
            if position < 0:
                continue
            path = (position,)
            try:
                iter = self.get_iter(path)
            except ValueError:
                continue
            self.row_changed(path, iter)

    def on_playback_state_change(self, event_type, player_obj, track):
        path = (self.playlist.current_position,)
        if path < 0 or path >= len(self):
            return
        try:
            iter = self.get_iter(path)
        except ValueError:
            return
        self.row_changed(path, iter)



