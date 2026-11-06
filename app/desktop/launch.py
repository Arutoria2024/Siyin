"""Single-instance Windows desktop entry."""
import ctypes, os, re, subprocess, sys, threading, time, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SiVoiceWorkbench.Desktop')
    from bootstrap import prepare
    prepare()
    kernel=ctypes.windll.kernel32
    kernel.CreateMutexW.restype=ctypes.c_void_p
    mutex=kernel.CreateMutexW(None,False,'Local\\SiVoiceWorkbenchDesktop')
    if kernel.GetLastError()==183:
        # Named window activation avoids opening another backend instance.
        hwnd=ctypes.windll.user32.FindWindowW(None,'祀音')
        if hwnd:ctypes.windll.user32.ShowWindow(hwnd,5);ctypes.windll.user32.SetForegroundWindow(hwnd)
        return
    import webview, pystray
    webview.settings['ALLOW_DOWNLOADS']=True
    from PIL import Image
    from desktop_server import ensure
    desktop=ensure(ROOT)
    base_url=desktop['base_url']
    class Bridge:
        def open_library(self):
            os.startfile(str(ROOT/'out/workbench'))
        def import_audio(self):
            import json, sqlite3, uuid, wave
            files=window.create_file_dialog(webview.OPEN_DIALOG,allow_multiple=False,file_types=('音频文件 (*.wav;*.mp3;*.flac;*.m4a;*.ogg)',))
            if not files:return None
            source=Path(files[0]);i=uuid.uuid4().hex;folder=ROOT/'out/workbench'/i;folder.mkdir()
            ffmpeg=ROOT/'tools/ffmpeg/ffmpeg.exe'
            subprocess.run([str(ffmpeg),'-v','error','-y','-i',str(source),'-ac','1','-ar','24000','-c:a','pcm_s16le','-threads','2',str(folder/'master.wav')],check=True,timeout=600,creationflags=0x08000000,capture_output=True)
            with wave.open(str(folder/'master.wav'),'rb') as f:duration=f.getnframes()/f.getframerate()
            with sqlite3.connect(ROOT/'out/workbench/library.sqlite') as c:c.execute('INSERT INTO tasks(id,title,text,voice,speed,sr,state,total,done,created,duration) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(i,source.stem,'','si',.88,24000,'completed',1,1,time.time(),duration))
            from identities import identity,migrate
            with sqlite3.connect(ROOT/'out/workbench/library.sqlite') as c:
                migrate(c)
                c.execute('UPDATE tasks SET source_type=?,title_source=?,identity=?,voice=? WHERE id=?',('import','filename',json.dumps(identity('', 'import'),ensure_ascii=False),'',i))
            return {'id':i}
    window=webview.create_window('祀音',base_url,js_api=Bridge(),width=1360,height=920,min_size=(1000,700),background_color='#F4F3EC')
    def set_native_icon():
        # pywebview 5.x ignores start(icon=...) on Windows and uses pythonw.exe.
        # before_show runs on the WinForms UI thread after the Form is created.
        from System.Drawing import Icon
        window._brand_icon=Icon(str(ROOT/'monitor/si-voice.ico'))
        window.native.Icon=window._brand_icon
        window.native.ShowIcon=True
        # WinForms disables default edit menus in production. Re-enable them
        # after WebView2 initialization without enabling debug/devtools.
        browser=window.native.browser.webview
        def enable_edit_menu(sender=None,args=None):
            if browser.CoreWebView2 is not None:
                browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled=True
        window._enable_edit_menu=enable_edit_menu
        if browser.CoreWebView2 is None:
            browser.CoreWebView2InitializationCompleted+=enable_edit_menu
        else:
            enable_edit_menu()
    window.events.before_show+=set_native_icon
    try:
        urllib.request.urlopen(urllib.request.Request(base_url+'/api/start',data=b'{}',headers={'X-Workbench-Token':desktop['token']}),timeout=5)
    except Exception:
        pass
    exiting=threading.Event()
    def close():
        if not exiting.is_set():window.hide();return False
    window.events.closing+=close
    def quit_app(icon,item):exiting.set();icon.stop();window.destroy()
    def stop_exit(icon,item):
        subprocess.run([str(ROOT/'python/python.exe'),str(ROOT/'desktop/stop_owned.py')],creationflags=0x08000000)
        quit_app(icon,item)
    icon=pystray.Icon('si',Image.open(ROOT/'monitor/si-voice.ico'),'祀音 · 语音工作台',menu=pystray.Menu(
        pystray.MenuItem('打开祀音工作台',lambda:window.show(),default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('停止服务并退出',stop_exit),
        pystray.MenuItem('退出应用',quit_app)))
    threading.Thread(target=icon.run,daemon=True).start()
    webview.start(gui='edgechromium', icon=str(ROOT/'monitor/si-voice.ico'))
    icon.stop()
if __name__=='__main__':main()
