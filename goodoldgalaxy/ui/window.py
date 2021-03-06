import os
import gi
import threading
import platform
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf,GLib, Gdk
from goodoldgalaxy.translation import _
from goodoldgalaxy.ui.login import Login
from goodoldgalaxy.ui.preferences import Preferences
from goodoldgalaxy.ui.about import About
from goodoldgalaxy.api import Api
from goodoldgalaxy.game import Game
from goodoldgalaxy.config import Config
from goodoldgalaxy.paths import UI_DIR, LOGO_IMAGE_PATH, THUMBNAIL_DIR, CACHE_DIR
from goodoldgalaxy.library import Library
from goodoldgalaxy.ui.installedrow import InstalledRow
from goodoldgalaxy.ui.downloadrow import DownloadRow
from goodoldgalaxy.ui.library import Library as LibraryView
from goodoldgalaxy.ui.details import Details
from zipfile import BadZipFile
from goodoldgalaxy.installer import uninstall_game, install_game
from goodoldgalaxy.download import Download
from goodoldgalaxy.download_manager import DownloadManager

@Gtk.Template.from_file(os.path.join(UI_DIR, "application.ui"))
class Window(Gtk.ApplicationWindow):

    __gtype_name__ = "Window"

    menu_about = Gtk.Template.Child()
    menu_preferences = Gtk.Template.Child()
    menu_logout = Gtk.Template.Child()
    user_photo = Gtk.Template.Child()
    installed_search = Gtk.Template.Child()
    selection_button = Gtk.Template.Child()
    selection_label = Gtk.Template.Child()
    selection_window = Gtk.Template.Child()
    installed_list = Gtk.Template.Child()
    downloads_button = Gtk.Template.Child()
    user_stack = Gtk.Template.Child()
    downloads_window = Gtk.Template.Child()
    installed_window = Gtk.Template.Child()
    downloads_list = Gtk.Template.Child()

    def __init__(self, name):
        Gtk.ApplicationWindow.__init__(self, title=name)
        self.api = Api()
        self.offline = False
        self.library = Library(self.api)
        self.games = []
        self.library_view = LibraryView(self,library=self.library,api=self.api)
        self.details = None
        
        res = self.get_screen_resolution()
        # we got resolution
        if res[0] > 0 and res[0] <= 1368:
            self.set_default_size(1024,700)   
        
        # Set the icon
        icon = GdkPixbuf.Pixbuf.new_from_file(LOGO_IMAGE_PATH)
        self.set_default_icon_list([icon])
        self.installed_search.connect("search-changed",self.filter_installed)
        self.selection_button.hide()

        # Show the window
        self.show_all()
        self.selection_button.hide()
        self.selection_label.set_text(_("Library"))

        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

        # Create the thumbnails directory
        if not os.path.exists(THUMBNAIL_DIR):
            os.makedirs(THUMBNAIL_DIR)

        # Interact with the API
        self.__authenticate()
        self.user_photo.set_tooltip_text(self.api.get_user_info(self.__set_avatar))
        self.sync_library()
        
        # Check what was the last view
        if Config.get("last_view") == "Game":
            print("last view as game..")
        else:
            self.__show_library()
            
        # Register self as a download manager listener
        DownloadManager.register_listener(self.__download_listener_func)

    def get_screen_resolution(self, measurement="px"):
        """
        Tries to detect the screen resolution from the system.
        @param measurement: The measurement to describe the screen resolution in. Can be either 'px', 'inch' or 'mm'. 
        @return: (screen_width,screen_height) where screen_width and screen_height are int types according to measurement.
        """
        mm_per_inch = 25.4
        try: # Platforms supported by GTK3, Fx Linux/BSD
            screen = Gdk.Screen.get_default()
            if measurement=="px":
                width = screen.get_width()
                height = screen.get_height()
            elif measurement=="inch":
                width = screen.get_width_mm()/mm_per_inch
                height = screen.get_height_mm()/mm_per_inch
            elif measurement=="mm":
                width = screen.get_width_mm()
                height = screen.get_height_mm()
            else:
                raise NotImplementedError("Handling %s is not implemented." % measurement)
            return (width,height)
        except Exception as ex:
            print("Could not obtain screen resolution. Cause: {}".format(ex))
            return (-1,-1)

    # Downloads if goodoldgalaxy was closed with this game downloading
    def resume_download_if_expected(self):
        download_id = Config.get("current_download")
        all_games = self.library.get_games()
        for game in all_games:
            if download_id and download_id == game.id and game.state != game.state.INSTALLED:
                self.download_game(game)

    # Do not restart the download if goodoldgalaxy is restarted
    def prevent_resume_on_startup(self,game):
        download_id = Config.get("current_download")
        if download_id and download_id == game.id:
            Config.unset("current_download")

    
    def __show_library(self):
        self.selection_button.hide()
        self.selection_label.set_text(_("Library"))
        # first remove any existing child
        if len(self.selection_window.get_children()) > 0:
            self.selection_window.remove(self.selection_window.get_children()[0])
        self.details = None
        self.selection_window.add(self.library_view)
        
    def update_library_view(self):
        self.library_view.update_library()
    
    def show_game_details(self,game: Game):
        self.selection_button.show()
        self.selection_label.set_text(game.name)
        # first remove any existing child
        if len(self.selection_window.get_children()) > 0:
            self.selection_window.remove(self.selection_window.get_children()[0])
        # destroy existing instance only if game is different
#        if self.details is not None and self.details.game.id != game.id:
#            self.details.destroy()
#            self.details = None
        # create a new instance only if necessary
        if self.details is None:
            self.details = Details(self,game,self.api)
        elif self.details is not None and self.details.game.id != game.id:
#            self.details = Details(self,game,self.api)
            self.details.set_game(game)
        # add details to selection window
        self.selection_window.add(self.details)
        self.selection_window.get_vadjustment().set_value(0)
    
    def __set_avatar(self):
        user_dir = os.path.join(CACHE_DIR, "user/{}".format(Config.get("user_id")))
        avatar = os.path.join(user_dir,"avatar_menu_user_av_small.jpg")
        if os.path.isfile(avatar) and os.path.exists(avatar):
            GLib.idle_add(self.user_photo.set_from_file, avatar)
            return True
        return False

    def filter_installed(self, widget):
        print("filter_installed")
#        if (self.library is not None):
#            Config.set("filter_installed", False if switch.get_state() else True)
#            self.show_installed_only = False if switch.get_state() else True
#            self.library.filter_library(switch)

    def install_game(self,game: Game):
        # used to say that a game was installed
        # add to the sidebar
        if game.sidebar_tile is not None:
            return
        # add it to the sidebar
        game.sidebar_tile = InstalledRow(self, game, self.api)
        GLib.idle_add(self.installed_list.prepend,game.sidebar_tile)
        install_thread = threading.Thread(target=self.__install,args=[game])
        install_thread.start()
            
    def uninstall_game(self, game: Game) -> bool:
        message_dialog = Gtk.MessageDialog(parent=self,
                                           flags=Gtk.DialogFlags.MODAL,
                                           message_type=Gtk.MessageType.WARNING,
                                           buttons=Gtk.ButtonsType.OK_CANCEL,
                                           message_format=_("Are you sure you want to uninstall %s?" % game.name))
        response = message_dialog.run()

        if response == Gtk.ResponseType.OK:
            uninstall_thread = threading.Thread(target=self.__uninstall_game,args=[game])
            uninstall_thread.start()
            message_dialog.destroy()
            return True
        elif response == Gtk.ResponseType.CANCEL:
            message_dialog.destroy()
        return False
            
    def __update_to_state(self, state, game: Game):
        game.state = state
        if game.list_tile is not None:
            game.list_tile.update_to_state(state)
        if game.grid_tile is not None:
            game.grid_tile.update_to_state(state)
        if game.sidebar_tile is not None:
            game.sidebar_tile.update_to_state(state)
        if self.details is not None and self.details.game == game:
            self.details.update_to_state(state)
                    
    def download_game(self, game: Game):
        if game.type == "game" and game.sidebar_tile is None:
            game.sidebar_tile = InstalledRow(self, game, self.api)
            GLib.idle_add(self.installed_list.prepend,game.sidebar_tile)
        # start download
        download_thread = threading.Thread(target=self.__download_file,args=[game])
        download_thread.start()

    def __download_file(self,game: Game, operating_system = None) -> None:
        Config.set("current_download", game.id)
        GLib.idle_add(self.__update_to_state, game.state.QUEUED, game)
        
        current_os = platform.system()
        if current_os == "Linux":
            current_os="linux"
        elif current_os == "Windows":
            current_os="windows"
        elif current_os == "Darwin":
            current_os="mac"
        # pick current os if none was passed
        if operating_system is None:
            operating_system = current_os
        if game.platform is None:
            game.platform = operating_system
        
        download_info = self.api.get_download_info(game,operating_system=operating_system)

        # Start the download for all files
        game.downloads = []
        download_path = game.download_path
        finish_func = self.__install
        for key, file_info in enumerate(download_info['files']):
            if key > 0:
                download_path = "{}-{}.bin".format(self.download_path, key)
            download = Download(
                url=self.api.get_real_download_link(file_info["downlink"]),
                title=download_info["name"],
                associated_object=game,
                save_location=download_path,
                number=key+1,
                file_size=download_info["total_size"],
                out_of_amount=len(download_info['files'])
            )
            download.register_finish_function(finish_func,game)
            download.register_progress_function(self.set_progress,game)
            download.register_cancel_function(self.__cancel_download,game)
            game.downloads.append(download)

        DownloadManager.download(game.downloads)

    def __install(self, game: Game = None):
        GLib.idle_add(self.__update_to_state, game.state.INSTALLING, game)
        game.install_dir = game.get_install_dir()
        try:
            if os.path.exists(game.keep_path):
                install_game(game, game.keep_path, main_window=self)
            else:
                install_game(game, game.download_path, main_window=self)
        except (FileNotFoundError, BadZipFile):
            GLib.idle_add(self.__update_to_state, game.state.DOWNLOADABLE, game)
            return
        GLib.idle_add(self.__update_to_state, game.state.INSTALLED, game)
        GLib.idle_add(self.__reload_state, game)
        # make user to add the game to the side bar
        
        # check if DLCs should also be installed
        if game.type == "game" and Config.get("install_dlcs"):
            # first ensure we know about game dlcs
            self.library.update_dlcs_for_game(game)
            if len(game.dlcs) == 0:
                return
            # now grab DLCs that can be installed
            downloads = []
            for dlc in game.dlcs:
                try:
                    download_info = self.api.get_download_info(dlc, game.platform, True, dlc.get_installers())
                except Exception:
                    # could not find a valid target, ignore it
                    continue
                # set dlc information now, otherwise this will break later
                dlc.platform = game.platform
                dlc.language = game.language
                # add download
                # Start the download for all files
                for key, file_info in enumerate(download_info['files']):
                    if key > 0:
                        download_path = "{}-{}.bin".format(dlc.download_path, key)
                    else:
                        download_path = dlc.download_path
                    download = Download(
                        url=self.api.get_real_download_link(file_info["downlink"]),
                        title=dlc.name,
                        associated_object=dlc,
                        save_location=download_path,
                        number=key+1,
                        file_size=download_info["total_size"],
                        out_of_amount=len(download_info['files'])
                    )
                    download.register_finish_function(self.__dlc_finish_func,[game,dlc])
                    download.register_progress_function(self.set_progress,game)
                    download.register_cancel_function(self.__cancel_download,game)
                    downloads.append(download)
            DownloadManager.download(downloads)
                    
    def __dlc_finish_func(self, args):
        game = args[0]
        dlc = args[1]
        if dlc is None:
            return
        # install DLC
        try:
            if os.path.exists(dlc.keep_path):
                install_game(dlc, dlc.keep_path, main_window=self)
            else:
                install_game(dlc, dlc.download_path, main_window=self)
        except (FileNotFoundError, BadZipFile):
            # error, revert state
            return
        # No error, install was successful, as such update information
        game.set_dlc_status(dlc.name, "installed" , dlc.available_version)

    def __reload_state(self,game: Game = None):
        if game.list_tile is not None:
            game.list_tile.reload_state()
        if game.grid_tile is not None:
            game.grid_tile.reload_state()
        if game.sidebar_tile is not None:
            game.sidebar_tile.reload_state()

    def cancel_download(self, game: Game = None):
        message_dialog = Gtk.MessageDialog(parent=self,
                                           flags=Gtk.DialogFlags.MODAL,
                                           message_type=Gtk.MessageType.WARNING,
                                           buttons=Gtk.ButtonsType.OK_CANCEL,
                                           message_format=_("Are you sure you want to cancel downloading {}?").format(game.name))
        response = message_dialog.run()

        if response == Gtk.ResponseType.OK:
            self.prevent_resume_on_startup(game)
            cancel_thread = threading.Thread(target=self.__cancel_download,args=[game])
            cancel_thread.start()
        message_dialog.destroy()

    def __cancel_download(self, game: Game = None):
        DownloadManager.cancel_download(game.downloads)
        GLib.idle_add(self.__reload_state,game)
        if game.state == game.state.DOWNLOADING:
            ## remove sidebar tile
            if game.sidebar_tile is not None:
                game.sidebar_tile.get_parent().get_parent().remove(game.sidebar_tile.get_parent())
                game.sidebar_tile = None
            GLib.idle_add(self.__update_to_state, game.state.DOWNLOADABLE, game)
        elif game.state == game.state.UPDATE_DOWNLOADING:
            GLib.idle_add(self.__update_to_state, game.state.INSTALLED, game)
    
    def download_update(self, game: Game):
        if game.sidebar_tile is None:
            game.sidebar_tile = InstalledRow(self, game, self.api)
            GLib.idle_add(self.installed_list.prepend,game.sidebar_tile)
        # start download
        download_thread = threading.Thread(target=self.__download_update,args=[game])
        download_thread.start()
        
    def __download_update(self,game: Game = None) -> None:
        Config.set("current_download", game.id)
        GLib.idle_add(self.__update_to_state, game.state.UPDATE_QUEUED, game)
        download_info = self.api.get_download_info(game)

        # Start the download for all files
        game.downloads = []
        download_path = game.update_path
        finish_func = self.__update
        for key, file_info in enumerate(download_info['files']):
            if key > 0:
                download_path = "{}-{}.bin".format(self.update_path, key)
            download = Download(
                url=self.api.get_real_download_link(file_info["downlink"]),
                save_location=download_path,
                finish_func=finish_func,
                finish_func_args=game,
                progress_func=self.set_progress,
                progress_func_args=game,
                cancel_func=self.__cancel_update,
                cancel_func_args=game,
                number=key+1,
                out_of_amount=len(download_info['files'])
            )
            game.downloads.append(download)

        DownloadManager.download(game.downloads)
        
    def __update(self, game: Game = None):
        GLib.idle_add(self.__update_to_state, game.state.UPDATING, game)
        game.install_dir = self.__get_install_dir(game)
        try:
            if os.path.exists(game.keep_path):
                install_game(self.game, self.keep_path, parent_window=self.parent)
            else:
                install_game(self.game, self.update_path, parent_window=self.parent)
        except (FileNotFoundError, BadZipFile):
            GLib.idle_add(self.__update_to_state, game.state.UPDATABLE, game)
            return
        # reset updates count flag
        game.updates = 0
        GLib.idle_add(self.__update_to_state, game.state.INSTALLED, game)

    def __cancel_update(self, game: Game = None):
        GLib.idle_add(self.__update_to_state, game.state.UPDATABLE, game)
        GLib.idle_add(self.__reload_state, game)

    def set_progress(self, percentage: int, game: Game = None):
        if game.state == game.state.QUEUED:
            GLib.idle_add(self.__update_to_state, game.state.DOWNLOADING, game)
        if game.state == game.state.UPDATE_QUEUED:
            GLib.idle_add(self.__update_to_state, game.state.UPDATE_DOWNLOADING, game)
        if game.sidebar_tile is not None and game.sidebar_tile.progress_bar:
            GLib.idle_add(game.sidebar_tile.progress_bar.set_fraction, percentage/100)
        if game.list_tile is not None and game.list_tile.progress_bar:
            GLib.idle_add(game.list_tile.progress_bar.set_fraction, percentage/100)
        if game.grid_tile is not None and game.grid_tile.progress_bar:
            GLib.idle_add(game.grid_tile.progress_bar.set_fraction, percentage/100)

    def __uninstall_game(self,game: Game = None):
        GLib.idle_add(self.__update_to_state, game.state.UNINSTALLING, game)
        # Remove game from sidebar if it is there
        if game.sidebar_tile is not None:
            self.installed_list.remove(game.sidebar_tile.get_parent())
            game.sidebar_tile = None
        uninstall_game(game)
        GLib.idle_add(self.__update_to_state, game.state.DOWNLOADABLE, game)
        
    def __update_downloads(self):
        # disabled now
        for child in self.downloads_list.get_children():
            self.downloads_list.remove(child)
    
        for download in DownloadManager.list():
            row = DownloadRow(self.downloads_list, download, self.api)
            GLib.idle_add(self.downloads_list.prepend,row)
    
    def __download_listener_func(self, download: Download = None):
        if download is None or download.priority() < 0:
            return
        # create a new download row
        row = DownloadRow(self.downloads_list, download, self.api)
        GLib.idle_add(self.downloads_list.prepend,row)

    @Gtk.Template.Callback("on_downloads_button_toogled")
    def on_downloads_button_toogled(self, button):
        if button.get_active():
            self.installed_window.hide()
            self.downloads_window.show()
            #self.__update_downloads()
            self.user_stack.set_visible_child_name("downloads_stack")
        else:
            self.installed_window.show()
            self.downloads_window.hide()
            self.user_stack.set_visible_child_name("installed_stack")


    @Gtk.Template.Callback("on_selection_button_clicked")
    def on_selection_button_clicked(self, button):
        self.__show_library()
        
    @Gtk.Template.Callback("on_menu_preferences_clicked")
    def show_preferences(self, button):
        preferences_window = Preferences(self)
        preferences_window.run()
        preferences_window.destroy()

    @Gtk.Template.Callback("on_menu_about_clicked")
    def show_about(self, button):
        about_window = About(self)
        about_window.run()
        about_window.destroy()

    @Gtk.Template.Callback("on_menu_logout_clicked")
    def logout(self, button):
        # Unset everything which is specific to this user
        Config.unset("username")
        Config.unset("user_id")
        Config.unset("refresh_token")
        self.hide()

        # Show the login screen
        self.__authenticate()
        self.user_photo.set_tooltip_text(self.api.get_user_info())
        self.user_photo.set_from_icon_name("contact-new",4)
        self.sync_library()

        self.show_all()

    def __sync_library(self):
        if self.library.offline:
            self.__authenticate()
        for child in self.installed_list.get_children():
            self.installed_list.remove(child)
        self.games=self.library.get_games(forced=True)
        for game in self.games:
            if game.installed == 0:
                continue
            if game.sidebar_tile is None:
                game.sidebar_tile = InstalledRow(self, game, self.api)
                GLib.idle_add(self.installed_list.prepend,game.sidebar_tile)
        # update library view
        self.update_library_view()
        
        # Start download if goodoldgalaxy was closed while downloading this game
        self.resume_download_if_expected()
    
    @Gtk.Template.Callback("on_menu_sync_clicked")
    def sync_library(self): 
        sync_thread = threading.Thread(target=self.__sync_library)
        sync_thread.start()

    """
    The API remembers the authentication token and uses it
    The token is not valid for a long time
    """
    def __authenticate(self):
        url = None
        if Config.get("stay_logged_in"):
            token = Config.get("refresh_token")
        else:
            Config.unset("username")
            Config.unset("user_id")
            Config.unset("refresh_token")
            token = None

        # Make sure there is an internet connection
        if not self.api.can_connect():
            return

        try:
            authenticated = self.api.authenticate(refresh_token=token, login_code=url)
        except Exception as ex:
            print("Could not authenticate with GOG. Cause: {}".format(ex))
            return

        while not authenticated:
            login_url = self.api.get_login_url()
            redirect_url = self.api.get_redirect_url()
            login = Login(login_url=login_url, redirect_url=redirect_url, parent=self)
            response = login.run()
            login.hide()
            if response == Gtk.ResponseType.DELETE_EVENT:
                Gtk.main_quit()
                exit(0)
            if response == Gtk.ResponseType.NONE:
                result = login.get_result()
                authenticated = self.api.authenticate(refresh_token=token, login_code=result)

        Config.set("refresh_token", authenticated)
