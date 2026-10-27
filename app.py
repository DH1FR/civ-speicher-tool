"""Icom Speicher-Tool fuer IC-9700 / IC-705 (Tkinter)."""
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import repeaters
import store
from memory import (MODELS, MODES, DUPLEX, TONEMODES, MHZ, Channel, convert_set)
from radio import open_radio

DEVICES = list(MODELS)          # ['ic9700', 'ic705']


def fmt_freq(hz):
    return f'{hz / MHZ:.5f}'.rstrip('0').rstrip('.') if hz else ''


class Progress(tk.Toplevel):
    """Fortschrittsfenster fuer Aktionen im Hintergrund (Verbinden, Lesen, Schreiben)."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.cancelled = False
        self.label = ttk.Label(self, text='Verbinde ...', width=50)
        self.label.pack(padx=14, pady=(14, 6))
        self.bar = ttk.Progressbar(self, length=360, mode='determinate')
        self.bar.pack(padx=14, pady=6)
        ttk.Button(self, text='Abbrechen', command=self._cancel).pack(pady=(6, 12))
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.grab_set()

    def _cancel(self):
        self.cancelled = True

    def update_state(self, text, value, total):
        self.label.config(text=text)
        self.bar.config(maximum=max(total, 1), value=value)


def run_bg(parent, title, work, done):
    """work(report) laeuft im Thread; report(text, i, n) -> False bei Abbruch.
    done(result, error) laeuft im GUI-Thread."""
    dlg = Progress(parent, title)
    state = {'msg': ('Verbinde ...', 0, 1), 'res': None, 'err': None, 'fin': False}

    def report(text, i, n):
        state['msg'] = (text, i, n)
        return not dlg.cancelled

    def target():
        try:
            state['res'] = work(report)
        except Exception as e:                     # noqa: BLE001 - Fehler an GUI weiterreichen
            state['err'] = e
        state['fin'] = True

    def poll():
        dlg.update_state(*state['msg'])
        if state['fin']:
            dlg.destroy()
            done(state['res'], state['err'])
        else:
            parent.after(100, poll)

    threading.Thread(target=target, daemon=True).start()
    poll()


class ChannelDialog(tk.Toplevel):
    def __init__(self, parent, model, ch, taken):
        super().__init__(parent)
        self.title('Speicher bearbeiten')
        self.transient(parent)
        self.model, self.taken, self.result, self.src = model, taken, None, ch
        self.vars = {}
        rows = [
            ('group', 'Gruppe' + (' (aus Band)' if model.band_groups else ''), ch.group),
            ('number', 'Kanal-Nr.', ch.number), ('name', 'Name (max. 16)', ch.name),
            ('freq', 'Frequenz MHz', fmt_freq(ch.freq)),
            ('mode', 'Betriebsart', ch.mode), ('filter', 'Filter (1-3)', ch.filter),
            ('datamode', 'Datenmodus (0/1)', ch.datamode),
            ('duplex', 'Duplex', ch.duplex), ('offset', 'Ablage MHz', fmt_freq(ch.offset) or '0'),
            ('tone_mode', 'Ton-Modus', ch.tone_mode), ('tone', 'Rufton Hz', ch.tone),
            ('tsql', 'Tonsquelch Hz', ch.tsql), ('dtcs', 'DTCS-Code', ch.dtcs),
            ('ur', 'UR (D-STAR)', ch.ur), ('r1', 'R1 Relais (D-STAR)', ch.r1),
            ('r2', 'R2 Gateway (D-STAR)', ch.r2), ('comment', 'Notiz', ch.comment),
        ]
        choices = {'mode': model.modes, 'duplex': DUPLEX, 'tone_mode': TONEMODES}
        for i, (key, label, val) in enumerate(rows):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky='w', padx=10, pady=2)
            v = tk.StringVar(value=str(val))
            self.vars[key] = v
            if key in choices:
                w = ttk.Combobox(self, textvariable=v, values=list(choices[key]), state='readonly', width=24)
            else:
                w = ttk.Entry(self, textvariable=v, width=27)
            w.grid(row=i, column=1, padx=10, pady=2)
        bf = ttk.Frame(self)
        bf.grid(row=len(rows), column=0, columnspan=2, pady=10)
        ttk.Button(bf, text='OK', command=self.ok).pack(side='left', padx=6)
        ttk.Button(bf, text='Abbrechen', command=self.destroy).pack(side='left', padx=6)
        self.grab_set()
        self.wait_window()

    def ok(self):
        g = {k: v.get().strip() for k, v in self.vars.items()}
        try:
            c = Channel.from_dict(self.src.to_dict())
            c.number = int(g['number'])
            c.group = int(g['group'])
            c.name = g['name'][:16]
            c.freq = round(float(g['freq'].replace(',', '.')) * MHZ)
            c.mode, c.duplex, c.tone_mode = g['mode'], g['duplex'], g['tone_mode']
            c.filter, c.datamode = int(g['filter']), int(g['datamode'])
            c.offset = round(float(g['offset'].replace(',', '.')) * MHZ)
            c.tone, c.tsql = float(g['tone']), float(g['tsql'])
            c.dtcs = int(g['dtcs'])
            c.ur, c.r1, c.r2, c.comment = g['ur'][:8], g['r1'][:8], g['r2'][:8], g['comment']
        except ValueError:
            messagebox.showerror('Eingabe', 'Ungueltiger Zahlenwert.', parent=self)
            return
        m = self.model
        if m.band_groups and m.group_for(c.freq):
            c.group = m.group_for(c.freq)
        if not m.group_range[0] <= c.group <= m.group_range[1]:
            messagebox.showerror('Eingabe', f'Gruppe muss {m.group_range[0]}-{m.group_range[1]} sein.', parent=self)
            return
        if not m.first <= c.number <= m.last:
            messagebox.showerror('Eingabe', f'Kanal-Nr. muss {m.first}-{m.last} sein.', parent=self)
            return
        if m.band_of(c.freq) is None:
            if not messagebox.askyesno('Frequenz', f'{fmt_freq(c.freq)} MHz liegt ausserhalb der Baender des '
                                       f'{m.title} (' + ('2 m / 70 cm / 23 cm' if m.key == 'ic9700'
                                                         else 'Kurzwelle bis 6 m / 2 m / 70 cm') +
                                       '). Trotzdem uebernehmen?', parent=self):
                return
        if (c.group, c.number) in self.taken and (c.group, c.number) != (self.src.group, self.src.number):
            if not messagebox.askyesno('Kanal belegt', f'Kanal {c.number} in Gruppe {c.group} ist belegt. Ersetzen?', parent=self):
                return
        self.result = c
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.title('Einstellungen')
        self.transient(parent)
        self.cfg, self.ok_pressed = cfg, False
        self.vars = {}
        r = 0
        for key in DEVICES:
            d = cfg['devices'][key]
            ttk.Label(self, text=MODELS[key].title, font=('', 10, 'bold')).grid(row=r, column=0, columnspan=2,
                                                                              sticky='w', padx=10, pady=(10, 2))
            r += 1
            for fld, label in (('host', 'IP-Adresse (oder "sim")'), ('user', 'Benutzer'), ('password', 'Passwort')):
                ttk.Label(self, text=label).grid(row=r, column=0, sticky='w', padx=10)
                v = tk.StringVar(value=d.get(fld, ''))
                self.vars[(key, fld)] = v
                ttk.Entry(self, textvariable=v, width=28, show='*' if fld == 'password' else '').grid(row=r, column=1, padx=10, pady=1)
                r += 1
        ttk.Label(self, text='Standort', font=('', 10, 'bold')).grid(row=r, column=0, sticky='w', padx=10, pady=(10, 2))
        r += 1
        q = cfg['qth']
        self.qth = tk.StringVar(value=q.get('text', ''))
        self.radius = tk.StringVar(value=str(q.get('radius_km', 50)))
        ttk.Label(self, text='Ort oder PLZ').grid(row=r, column=0, sticky='w', padx=10)
        ttk.Entry(self, textvariable=self.qth, width=28).grid(row=r, column=1, padx=10)
        r += 1
        ttk.Label(self, text='Radius km').grid(row=r, column=0, sticky='w', padx=10)
        ttk.Entry(self, textvariable=self.radius, width=28).grid(row=r, column=1, padx=10, pady=1)
        r += 1
        ttk.Label(self, text='Hinweis: Passwoerter liegen unverschluesselt in config.json.',
                  foreground='gray').grid(row=r, column=0, columnspan=2, padx=10, pady=4)
        r += 1
        bf = ttk.Frame(self)
        bf.grid(row=r, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text='OK', command=self.ok).pack(side='left', padx=6)
        ttk.Button(bf, text='Abbrechen', command=self.destroy).pack(side='left', padx=6)
        self.grab_set()
        self.wait_window()

    def ok(self):
        for (key, fld), v in self.vars.items():
            self.cfg['devices'][key][fld] = v.get().strip() if fld != 'password' else v.get()
        q = self.cfg['qth']
        text = self.qth.get().strip()
        if text != q.get('text'):
            q['lat'] = q['lon'] = None
        q['text'] = text
        try:
            q['radius_km'] = float(self.radius.get().replace(',', '.'))
        except ValueError:
            pass
        self.ok_pressed = True
        self.destroy()


class OwnRepeaterEdit(tk.Toplevel):
    """Ein eigenes Relais anlegen/aendern."""

    FIELDS = [('kind', 'Art'), ('call', 'Rufzeichen'), ('place', 'Ort / PLZ'), ('freq', 'Frequenz MHz'),
              ('duplex', 'Duplex'), ('offset', 'Ablage MHz'), ('tone_mode', 'Ton-Modus'), ('tone', 'Ton Hz'),
              ('rpt1', 'R1 Relais (D-STAR)'), ('gateway', 'Gateway (D-STAR)'), ('lat', 'Breite'), ('lon', 'Laenge')]

    def __init__(self, parent, item):
        super().__init__(parent)
        self.title('Eigenes Relais')
        self.transient(parent)
        self.result = None
        d = item or {'kind': 'FM', 'duplex': 'DUP-', 'tone_mode': 'OFF', 'tone': 88.5, 'offset': 600_000}
        self.vars = {}
        choices = {'kind': ['FM', 'DSTAR'], 'duplex': DUPLEX[:3], 'tone_mode': ['OFF', 'TONE', 'TSQL']}
        for i, (key, label) in enumerate(self.FIELDS):
            val = d.get(key, '')
            if key in ('freq', 'offset'):
                val = fmt_freq(int(val)) if val else ''
            ttk.Label(self, text=label).grid(row=i, column=0, sticky='w', padx=10, pady=2)
            v = tk.StringVar(value=str(val))
            self.vars[key] = v
            if key in choices:
                w = ttk.Combobox(self, textvariable=v, values=choices[key], state='readonly', width=22)
            else:
                w = ttk.Entry(self, textvariable=v, width=25)
            w.grid(row=i, column=1, padx=10, pady=2)
        r = len(self.FIELDS)
        pf = ttk.Frame(self)
        pf.grid(row=r, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(pf, text='Position aus Ort/PLZ', command=self.geo).pack(side='left', padx=4)
        ttk.Button(pf, text='Position von Relais (Rufzeichen)', command=self.like).pack(side='left', padx=4)
        ttk.Label(self, text='Position: entweder Breite/Laenge eintragen oder ueber die Knoepfe ermitteln.\n'
                             '"Von Relais" nimmt die Position eines bekannten Relais, dessen Rufzeichen du eingibst '
                             '(z. B. DB0KH).', foreground='gray', justify='left').grid(row=r + 1, column=0, columnspan=2,
                                                                                       padx=10, pady=4)
        bf = ttk.Frame(self)
        bf.grid(row=r + 2, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text='OK', command=self.ok).pack(side='left', padx=6)
        ttk.Button(bf, text='Abbrechen', command=self.destroy).pack(side='left', padx=6)
        self.grab_set()
        self.wait_window()

    def geo(self):
        try:
            lat, lon, name = repeaters.geocode(self.vars['place'].get().strip())
        except (OSError, ValueError) as e:
            messagebox.showerror('Position', str(e), parent=self)
            return
        self.vars['lat'].set(f'{lat:.5f}')
        self.vars['lon'].set(f'{lon:.5f}')

    def like(self):
        call = simpledialog.askstring('Position von Relais', 'Rufzeichen des Relais am gleichen Standort:',
                                      initialvalue=self.vars['call'].get(), parent=self)
        if not call:
            return
        pos = repeaters.find_position(call)
        if not pos:
            messagebox.showinfo('Position', f'{call} nicht in den Online-Listen gefunden.', parent=self)
            return
        self.vars['lat'].set(f'{pos[0]:.5f}')
        self.vars['lon'].set(f'{pos[1]:.5f}')
        if not self.vars['place'].get().strip():
            self.vars['place'].set(pos[2])

    def ok(self):
        g = {k: v.get().strip() for k, v in self.vars.items()}
        try:
            d = {'kind': g['kind'], 'call': g['call'].upper(), 'place': g['place'],
                 'freq': round(float(g['freq'].replace(',', '.')) * MHZ),
                 'duplex': g['duplex'], 'offset': round(float((g['offset'] or '0').replace(',', '.')) * MHZ),
                 'tone_mode': g['tone_mode'], 'tone': float((g['tone'] or '88.5').replace(',', '.')),
                 'rpt1': g['rpt1'][:8], 'gateway': g['gateway'][:8],
                 'lat': float(g['lat'].replace(',', '.')), 'lon': float(g['lon'].replace(',', '.'))}
        except ValueError:
            messagebox.showerror('Eingabe', 'Frequenz, Ablage, Ton und Position muessen Zahlen sein '
                                 '(Position ggf. ueber die Knoepfe ermitteln).', parent=self)
            return
        if not d['call']:
            messagebox.showerror('Eingabe', 'Rufzeichen fehlt.', parent=self)
            return
        if d['kind'] == 'DSTAR':
            d['rpt1'] = d['rpt1'] or (d['call'] + ' B')[:8]
            d['gateway'] = d['gateway'] or (d['call'] + ' G')[:8]
        self.result = d
        self.destroy()


class OwnRepeatersDialog(tk.Toplevel):
    """Liste eigener Relais verwalten (ergaenzt die Online-Listen)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title('Eigene Relais')
        self.geometry('760x360')
        self.transient(parent)
        self.items = repeaters.load_own()
        cols = ('call', 'kind', 'place', 'freq', 'dup', 'tone')
        self.tree = ttk.Treeview(self, columns=cols, show='headings', selectmode='browse')
        for c, t, w in (('call', 'Rufzeichen', 90), ('kind', 'Art', 60), ('place', 'Ort', 220), ('freq', 'MHz', 90),
                        ('dup', 'Ablage', 100), ('tone', 'Ton', 80)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w')
        self.tree.pack(fill='both', expand=True, padx=8, pady=8)
        self.tree.bind('<Double-1>', lambda e: self.edit())
        bf = ttk.Frame(self)
        bf.pack(pady=6)
        for text, cmd in (('Neu', self.add), ('Aendern', self.edit), ('Loeschen', self.delete), ('Schliessen', self.destroy)):
            ttk.Button(bf, text=text, command=cmd).pack(side='left', padx=6)
        self.fill()
        self.grab_set()
        self.wait_window()

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(self.items):
            dup = ({'DUP-': '-', 'DUP+': '+'}.get(d.get('duplex'), '') + fmt_freq(d.get('offset', 0))) if d.get('duplex') in ('DUP-', 'DUP+') else ''
            tone = f"{d.get('tone', 0):g}" if d.get('tone_mode') in ('TONE', 'TSQL') else ''
            self.tree.insert('', 'end', iid=str(i), values=(d['call'], 'D-STAR' if d['kind'] == 'DSTAR' else 'FM',
                                                            d.get('place', ''), fmt_freq(d['freq']), dup, tone))

    def _save(self):
        repeaters.save_own(self.items)
        self.fill()

    def add(self):
        d = OwnRepeaterEdit(self, None).result
        if d:
            self.items.append(d)
            self._save()

    def edit(self):
        sel = self.tree.selection()
        if sel:
            d = OwnRepeaterEdit(self, self.items[int(sel[0])]).result
            if d:
                self.items[int(sel[0])] = d
                self._save()

    def delete(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno('Loeschen', 'Eigenes Relais loeschen?', parent=self):
            del self.items[int(sel[0])]
            self._save()


class RepeaterDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.title(f'Relais suchen - {app.model.title}')
        self.geometry('820x480')
        self.transient(parent)
        self.app, self.found, self.result = app, [], None
        top = ttk.Frame(self)
        top.pack(fill='x', padx=8, pady=6)
        q = app.cfg['qth']
        self.place = tk.StringVar(value=q.get('text', ''))
        self.radius = tk.StringVar(value=str(q.get('radius_km', 50)))
        self.fm = tk.BooleanVar(value=True)
        self.ds = tk.BooleanVar(value=True)
        ttk.Label(top, text='Ort/PLZ').pack(side='left')
        ttk.Entry(top, textvariable=self.place, width=22).pack(side='left', padx=4)
        ttk.Label(top, text='Radius km').pack(side='left')
        ttk.Entry(top, textvariable=self.radius, width=6).pack(side='left', padx=4)
        ttk.Checkbutton(top, text='FM', variable=self.fm).pack(side='left', padx=4)
        ttk.Checkbutton(top, text='D-STAR', variable=self.ds).pack(side='left', padx=4)
        ttk.Button(top, text='Suchen', command=self.search).pack(side='left', padx=8)
        bands = '2 m, 70 cm' + (', 23 cm' if app.model.key == 'ic9700' else ' (23 cm gibt es nur im IC-9700)')
        ttk.Label(self, text=f'Baender: {bands}', foreground='gray').pack(anchor='w', padx=10)
        gf = ttk.Frame(self)
        gf.pack(fill='x', padx=8, pady=(4, 0))
        ttk.Label(gf, text='Ziel-Gruppe (Start):').pack(side='left')
        m = app.model
        self.start_group = app.cur_group()
        self.gcombo = ttk.Combobox(gf, state='readonly', width=34)
        if m.band_groups:        # IC-9700: Gruppe ergibt sich aus dem Band
            self.gcombo.set('automatisch nach Band (2 m / 70 cm / 23 cm)')
            self.gcombo.config(state='disabled')
        else:
            self.gcombo.config(values=[app.glabel(g) for g in m.groups()])
            self.gcombo.current(m.groups().index(self.start_group))
            ttk.Label(gf, text='Ist sie voll, geht es in der naechsten Gruppe weiter.', foreground='gray').pack(side='left', padx=8)
        self.gcombo.pack(side='left', padx=4)
        cols = ('call', 'place', 'kind', 'freq', 'dup', 'tone', 'dist')
        self.tree = ttk.Treeview(self, columns=cols, show='headings', selectmode='extended')
        for c, t, w in (('call', 'Rufzeichen', 90), ('place', 'Standort', 200), ('kind', 'Art', 60),
                        ('freq', 'MHz', 90), ('dup', 'Ablage', 110), ('tone', 'Ton', 70), ('dist', 'km', 60)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w')
        self.tree.pack(fill='both', expand=True, padx=8, pady=6)
        bf = ttk.Frame(self)
        bf.pack(pady=6)
        ttk.Button(bf, text='Eigene Relais ...', command=self.own).pack(side='left', padx=6)
        ttk.Button(bf, text='Alle markieren', command=lambda: self.tree.selection_set(self.tree.get_children())).pack(side='left', padx=6)
        ttk.Button(bf, text='Auswahl in Speichersatz uebernehmen', command=self.take).pack(side='left', padx=6)
        ttk.Button(bf, text='Schliessen', command=self.destroy).pack(side='left', padx=6)
        self.status = ttk.Label(self, text='')
        self.status.pack(anchor='w', padx=10, pady=(0, 6))
        self.grab_set()
        self.wait_window()

    def search(self):
        kinds = tuple(k for k, v in (('FM', self.fm), ('DSTAR', self.ds)) if v.get())
        place = self.place.get().strip()
        try:
            radius = float(self.radius.get().replace(',', '.'))
        except ValueError:
            messagebox.showerror('Eingabe', 'Radius ungueltig.', parent=self)
            return
        if not place or not kinds:
            messagebox.showinfo('Suche', 'Ort/PLZ und mindestens eine Art waehlen.', parent=self)
            return
        qth = self.app.cfg['qth']
        model = self.app.model

        def work(report):
            report('Standort ermitteln ...', 0, 3)
            if qth.get('lat') is None or qth.get('text') != place:
                qth['lat'], qth['lon'], disp = geo = repeaters.geocode(place)
                qth['text'] = place
            report('Relaislisten laden ...', 1, 3)
            res = repeaters.search(qth['lat'], qth['lon'], radius, model, kinds)
            report('fertig', 3, 3)
            return res

        def done(res, err):
            if err:
                messagebox.showerror('Relaissuche', str(err), parent=self)
                return
            qth['radius_km'] = radius
            store.save_config(self.app.cfg)
            self.found = res
            self.tree.delete(*self.tree.get_children())
            for i, r in enumerate(res):
                dup = {'DUP-': '-', 'DUP+': '+'}.get(r.duplex, '') + (fmt_freq(r.offset) if r.duplex != 'OFF' else '')
                self.tree.insert('', 'end', iid=str(i), values=(
                    r.call, r.place, ('D-STAR' if r.kind == 'DSTAR' else 'FM') + (' *' if r.own else ''), fmt_freq(r.freq), dup,
                    f'{r.tone:g}' if r.tone_mode in ('TONE', 'TSQL') else '', f'{r.dist_km:.0f}'))
            self.status.config(text=f'{len(res)} Relais im Umkreis von {radius:g} km (Luftlinie, ohne Sichtverbindungspruefung)')

        run_bg(self, 'Relaissuche', work, done)

    def own(self):
        OwnRepeatersDialog(self)
        if self.found:
            self.search()          # Ergebnis mit den geaenderten eigenen Relais neu aufbauen

    def take(self):
        sel = [self.found[int(i)] for i in self.tree.selection()]
        if not sel:
            messagebox.showinfo('Relais', 'Bitte zuerst Relais in der Liste markieren (oder "Alle markieren").', parent=self)
            return
        self.result = sel
        if not self.app.model.band_groups:
            self.start_group = self.app.model.groups()[self.gcombo.current()]
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Icom Speicher-Tool - IC-9700 / IC-705')
        self.geometry('1100x620')
        self.cfg = store.load_config()
        self.dev = tk.StringVar(value=DEVICES[0])
        self.set_name = None
        self.channels = []
        self.group_names = {}
        self.gfilter = None            # None = alle Gruppen
        self.dirty = False             # ungespeicherte Aenderungen im aktuellen Satz
        self._build()
        self.refresh_sets()
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.bind('<Control-s>', lambda e: self.save())

    @property
    def model(self):
        return MODELS[self.dev.get()]

    # -- Aufbau
    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=8, pady=6)
        ttk.Label(bar, text='Geraet:').pack(side='left')
        cb = ttk.Combobox(bar, state='readonly', width=10, values=[MODELS[k].title for k in DEVICES])
        cb.set(self.model.title)
        cb.pack(side='left', padx=4)
        cb.bind('<<ComboboxSelected>>', lambda e: self.switch_device())
        self.devbox = cb
        ttk.Button(bar, text='Speichern', command=self.save).pack(side='left', padx=(20, 4))
        ttk.Button(bar, text='Vom Geraet lesen', command=self.read_radio).pack(side='left', padx=(4, 4))
        ttk.Button(bar, text='Auf Geraet schreiben', command=self.write_radio).pack(side='left', padx=4)
        ttk.Button(bar, text='Im Geraet loeschen ...', command=self.delete_in_radio).pack(side='left', padx=4)
        ttk.Button(bar, text='Einstellungen', command=self.settings).pack(side='right')

        body = ttk.PanedWindow(self, orient='horizontal')
        body.pack(fill='both', expand=True, padx=8, pady=4)
        left = ttk.Frame(body)
        body.add(left, weight=1)
        ttk.Label(left, text='Speichersaetze', font=('', 10, 'bold')).pack(anchor='w')
        self.sets = tk.Listbox(left, exportselection=False, width=28)
        self.sets.pack(fill='both', expand=True, pady=4)
        self.sets.bind('<<ListboxSelect>>', lambda e: self.on_set_select())
        for text, cmd in (('Neu', self.new_set), ('Umbenennen', self.rename_set), ('Loeschen', self.delete_set),
                          ('Ganzen Satz auf anderes Geraet kopieren', self.copy_set)):
            ttk.Button(left, text=text, command=cmd).pack(fill='x', pady=1)

        right = ttk.Frame(body)
        body.add(right, weight=4)
        self.header = ttk.Label(right, text='Kein Satz gewaehlt', font=('', 10, 'bold'))
        self.header.pack(anchor='w')
        gf = ttk.Frame(right)
        gf.pack(fill='x', pady=2)
        ttk.Label(gf, text='Gruppe:').pack(side='left')
        self.gbox = ttk.Combobox(gf, state='readonly', width=30)
        self.gbox.pack(side='left', padx=4)
        self.gbox.bind('<<ComboboxSelected>>', lambda e: self.pick_group())
        ttk.Button(gf, text='Gruppe benennen', command=self.name_group).pack(side='left', padx=4)
        ttk.Button(gf, text='Gruppe im Satz leeren', command=self.clear_group_in_set).pack(side='left', padx=4)
        cols = ('grp', 'nr', 'name', 'freq', 'mode', 'dup', 'tone', 'dv', 'note')
        self.tree = ttk.Treeview(right, columns=cols, show='headings', selectmode='extended')
        for c, t, w in (('grp', 'Gruppe', 110), ('nr', 'Nr.', 45), ('name', 'Name', 150), ('freq', 'Frequenz MHz', 110), ('mode', 'Mode', 60),
                        ('dup', 'Ablage', 100), ('tone', 'Ton', 90), ('dv', 'D-STAR (UR / R1 / R2)', 200), ('note', 'Notiz', 150)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w')
        self.tree.pack(fill='both', expand=True, pady=4)
        self.tree.bind('<Double-1>', lambda e: self.edit_channel())
        self.tree.bind('<Delete>', lambda e: self.delete_channels())
        self.tree.bind('<Control-a>', lambda e: (self.tree.selection_set(self.tree.get_children()), 'break')[1])
        self.tree.bind('<Alt-Up>', lambda e: (self.move_channels(-1), 'break')[1])
        self.tree.bind('<Alt-Down>', lambda e: (self.move_channels(1), 'break')[1])
        bf = ttk.Frame(right)
        bf.pack(fill='x')
        for text, cmd in (('Neuer Speicher', self.add_channel), ('Aendern', self.edit_channel),
                          ('Loeschen', self.delete_channels), ('▲ Hoch', lambda: self.move_channels(-1)),
                          ('▼ Runter', lambda: self.move_channels(1)), ('Sortieren ...', self.sort_channels),
                          ('Markierte auf anderes Geraet kopieren', lambda: self.copy_set(True)),
                          ('Relais suchen ...', self.find_repeaters)):
            ttk.Button(bf, text=text, command=cmd).pack(side='left', padx=3, pady=3)
        self.status = ttk.Label(self, text='', relief='sunken', anchor='w')
        self.status.pack(fill='x', side='bottom')

    # -- Speichersaetze
    def refresh_sets(self, select=None):
        self.sets.delete(0, 'end')
        names = store.list_sets(self.dev.get())
        for n in names:
            self.sets.insert('end', n)
        self.set_name, self.channels, self.group_names = None, [], {}
        self.dirty = False
        if select in names:
            self.sets.selection_set(names.index(select))
            self.pick_set()
        else:
            self.show()

    def reload_list(self):
        """Satzliste neu einlesen, ohne den geoeffneten Satz zu veraendern."""
        names = store.list_sets(self.dev.get())
        self.sets.delete(0, 'end')
        for n in names:
            self.sets.insert('end', n)
        if self.set_name in names:
            self.sets.selection_set(names.index(self.set_name))

    def on_set_select(self):
        sel = self.sets.curselection()
        if not sel or self.sets.get(sel[0]) == self.set_name:
            return
        if not self.confirm_discard():
            self.reload_list()                 # alte Auswahl wiederherstellen
            return
        self.pick_set()

    def switch_device(self):
        key = DEVICES[self.devbox.current()]
        if key == self.dev.get():
            return
        if not self.confirm_discard():
            self.devbox.set(self.model.title)
            return
        self.dev.set(key)
        self.refresh_sets()

    def save(self):
        if not self.set_name:
            return
        store.save_set(self.dev.get(), self.set_name, self.channels, self.group_names)
        self.dirty = False
        self.show()
        self.status.config(text=f'Satz "{self.set_name}" gespeichert')

    def confirm_discard(self):
        """True, wenn weitergemacht werden darf (gespeichert oder verworfen)."""
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel('Ungespeicherte Aenderungen',
                                        f'Satz "{self.set_name}" wurde geaendert.'
                                        ' Jetzt speichern?  (Nein = Aenderungen verwerfen)')
        if ans is None:
            return False
        if ans:
            self.save()
        self.dirty = False
        return True

    def on_close(self):
        if self.confirm_discard():
            self.destroy()

    def pick_set(self):
        sel = self.sets.curselection()
        if not sel:
            return
        self.set_name = self.sets.get(sel[0])
        self.channels, self.group_names = store.load_set(self.dev.get(), self.set_name)
        self.gfilter = None
        self.show()

    def glabel(self, g):
        name = self.group_names.get(g) or self.model.default_label(g)
        return f'{g}: {name}' if name else f'{g}'

    def group_list(self):
        m = self.model
        if m.band_groups:
            return m.groups()
        return sorted({c.group for c in self.channels} | {m.group} | ({self.gfilter} if self.gfilter is not None else set()))

    def pick_group(self):
        i = self.gbox.current()
        self.gfilter = None if i <= 0 else self.group_list()[i - 1]
        self.show()

    def name_group(self):
        if not self.need_set():
            return
        g = self.gfilter
        if g is None:
            g = simpledialog.askinteger('Gruppe benennen', 'Gruppennummer:', parent=self,
                                        minvalue=self.model.group_range[0], maxvalue=self.model.group_range[1])
            if g is None:
                return
        name = simpledialog.askstring('Gruppe benennen', f'Name fuer Gruppe {g}:', parent=self,
                                      initialvalue=self.group_names.get(g, self.model.default_label(g)))
        if name is None:
            return
        self.group_names[g] = name.strip()
        self.persist()

    def show(self):
        self.tree.delete(*self.tree.get_children())
        self.header.config(text=(f'{self.model.title}: {self.set_name}' + (' *  (nicht gespeichert)' if self.dirty else ''))
                           if self.set_name else 'Kein Satz gewaehlt')
        groups = self.group_list()
        self.gbox.config(values=['Alle Gruppen'] + [self.glabel(g) for g in groups])
        self.gbox.current(0 if self.gfilter is None or self.gfilter not in groups else groups.index(self.gfilter) + 1)
        shown = 0
        for c in sorted(self.channels, key=lambda c: (c.group, c.number)):
            if self.gfilter is not None and c.group != self.gfilter:
                continue
            dup = ({'DUP-': '-', 'DUP+': '+'}.get(c.duplex, '') + fmt_freq(c.offset)) if c.duplex != 'OFF' else ''
            tone = {'TONE': f'T {c.tone:g}', 'TSQL': f'TSQL {c.tsql:g}', 'DTCS': f'DTCS {c.dtcs:03d}'}.get(c.tone_mode, '')
            dv = f'{c.ur} / {c.r1} / {c.r2}' if c.mode == 'DV' else ''
            self.tree.insert('', 'end', iid=f'{c.group}:{c.number}', values=(
                self.glabel(c.group), c.number, c.name, fmt_freq(c.freq), c.mode, dup, tone, dv, c.comment))
            shown += 1
        self.status.config(text=f'{shown} von {len(self.channels)} Speichern angezeigt')

    def selected_keys(self):
        return {tuple(int(x) for x in i.split(':')) for i in self.tree.selection()}

    def persist(self):
        """Aenderung merken; gespeichert wird erst auf Nachfrage (Speichern, Wechsel, Beenden)."""
        self.dirty = True
        self.show()

    def need_set(self):
        if not self.set_name:
            messagebox.showinfo('Speichersatz', 'Bitte zuerst links einen Speichersatz waehlen oder neu anlegen.')
            return False
        return True

    def new_set(self):
        if not self.confirm_discard():
            return
        name = simpledialog.askstring('Neuer Speichersatz', 'Name:', parent=self)
        if not name:
            return
        if store.exists(self.dev.get(), name):
            messagebox.showerror('Speichersatz', 'Name existiert bereits.')
            return
        store.save_set(self.dev.get(), name, [])
        self.refresh_sets(name)

    def rename_set(self):
        if not self.need_set() or not self.confirm_discard():
            return
        name = simpledialog.askstring('Umbenennen', 'Neuer Name:', initialvalue=self.set_name, parent=self)
        if not name or name == self.set_name:
            return
        if store.exists(self.dev.get(), name):
            messagebox.showerror('Speichersatz', 'Name existiert bereits.')
            return
        store.rename_set(self.dev.get(), self.set_name, name)
        self.refresh_sets(name)

    def delete_set(self):
        if self.need_set() and messagebox.askyesno('Loeschen', f'Speichersatz "{self.set_name}" loeschen?'):
            store.delete_set(self.dev.get(), self.set_name)
            self.dirty = False
            self.refresh_sets()

    def copy_set(self, selected_only=False):
        """Ganzen Satz oder nur die markierten Speicher auf das andere Geraet kopieren."""
        if not self.need_set():
            return
        src = self.model
        dst = MODELS[[k for k in DEVICES if k != src.key][0]]
        chans = self.channels
        if selected_only:
            sel = self.selected_keys()
            if not sel:
                messagebox.showinfo('Kopieren', 'Bitte zuerst in der Tabelle einen oder mehrere Speicher markieren '
                                    '(Strg/Umschalt fuer mehrere).')
                return
            chans = [c for c in self.channels if (c.group, c.number) in sel]
        what = f'{len(chans)} markierte Speicher' if selected_only else f'Satz "{self.set_name}"'
        name = simpledialog.askstring('Kopieren', f'{what} von {src.title} nach {dst.title} kopieren.\n\n'
                                      f'Name des Satzes am {dst.title} (vorhandener Satz moeglich):',
                                      initialvalue=self.set_name, parent=self)
        if not name:
            return
        existing, names = [], {}
        if store.exists(dst.key, name):
            ans = messagebox.askyesnocancel('Kopieren', f'"{name}" existiert am {dst.title}.\n\n'
                                            'Ja = zu dem Satz hinzufuegen (Zusammenfuehren)\n'
                                            'Nein = Satz ersetzen\nAbbrechen = nichts tun')
            if ans is None:
                return
            if ans:
                existing, names = store.load_set(dst.key, name)
        out, skipped = convert_set(chans, src, dst, existing)
        store.save_set(dst.key, name, existing + out, names)
        msg = f'{len(out)} Speicher nach {dst.title} / "{name}" kopiert.'
        if skipped:
            msg += f'\n\n{len(skipped)} Hinweise:\n' + '\n'.join(skipped[:15]) + ('\n...' if len(skipped) > 15 else '')
        messagebox.showinfo('Kopieren', msg)

    # -- Kanaele
    def cur_group(self):
        return self.gfilter if self.gfilter is not None else self.model.group

    def next_free(self, group):
        used = {c.number for c in self.channels if c.group == group}
        m = self.model
        return next((n for n in range(m.first, m.last + 1) if n not in used), None)

    def add_channel(self):
        if not self.need_set():
            return
        g = self.cur_group()
        n = self.next_free(g)
        if n is None:
            messagebox.showinfo('Speicher', f'Alle Kanalnummern in Gruppe {g} belegt.')
            return
        self.edit(Channel(number=n, group=g))

    def edit_channel(self):
        sel = self.selected_keys()
        if self.need_set() and sel:
            g, n = next(iter(sel))
            self.edit(next(c for c in self.channels if (c.group, c.number) == (g, n)))

    def edit(self, ch):
        taken = {(c.group, c.number) for c in self.channels}
        d = ChannelDialog(self, self.model, ch, taken)
        if d.result:
            drop = {(ch.group, ch.number), (d.result.group, d.result.number)}
            self.channels = [c for c in self.channels if (c.group, c.number) not in drop] + [d.result]
            self.persist()

    def delete_channels(self):
        sel = self.selected_keys()
        if sel and self.need_set() and messagebox.askyesno('Loeschen', f'{len(sel)} Speicher aus dem Satz loeschen?'):
            self.channels = [c for c in self.channels if (c.group, c.number) not in sel]
            self.persist()

    def move_channels(self, delta):
        """Markierte Speicher um eine Nummer nach oben (-1) oder unten (+1) verschieben.
        Ist die Zielnummer frei, rueckt der Speicher dorthin, sonst tauschen beide die Nummer."""
        sel = self.selected_keys()
        if not sel or not self.need_set():
            return
        m = self.model
        by_key = {(c.group, c.number): c for c in self.channels}
        moved, fixed = set(), set()       # moved: neue Plaetze der Markierten; fixed: nicht verschiebbare
        # Vorderste Markierte zuerst, damit markierte Bloecke zusammenbleiben
        for g, n in sorted(sel, key=lambda k: (k[0], -k[1] * delta)):
            t = n + delta
            if not m.first <= t <= m.last or (g, t) in fixed:
                fixed.add((g, n))
                moved.add((g, n))
                continue
            c = by_key.pop((g, n))
            other = by_key.pop((g, t), None)
            if other is not None:             # Zielnummer belegt: Nummern tauschen
                other.number = n
                by_key[(g, n)] = other
            c.number = t
            by_key[(g, t)] = c
            moved.add((g, t))
        self.channels = list(by_key.values())
        self.persist()
        keep = [f'{c.group}:{c.number}' for c in self.channels if (c.group, c.number) in moved]
        keep = [k for k in keep if self.tree.exists(k)]
        self.tree.selection_set(keep)
        if keep:
            self.tree.see(keep[0])

    def sort_channels(self):
        if not self.need_set():
            return
        dlg = tk.Toplevel(self)
        dlg.title('Sortieren')
        dlg.transient(self)
        key = tk.StringVar(value='Name')
        scope = tk.StringVar(value='Gruppe' if self.gfilter is not None else 'Alle')
        ttk.Label(dlg, text='Sortieren nach:').grid(row=0, column=0, sticky='w', padx=10, pady=(10, 2))
        ttk.Combobox(dlg, textvariable=key, values=['Name', 'Frequenz', 'Betriebsart, Name'], state='readonly',
                     width=20).grid(row=0, column=1, padx=10, pady=(10, 2))
        ttk.Label(dlg, text='Bereich:').grid(row=1, column=0, sticky='w', padx=10, pady=2)
        ttk.Combobox(dlg, textvariable=scope, values=['Alle', 'Gruppe'], state='readonly', width=20).grid(row=1, column=1, padx=10, pady=2)
        ttk.Label(dlg, text='"Gruppe" = nur die oben gewaehlte Gruppe; "Alle" = jede Gruppe fuer sich.\n'
                            'Die Speicher werden lueckenlos ab Kanal ' + str(self.model.first) + ' neu nummeriert.',
                  foreground='gray', justify='left').grid(row=2, column=0, columnspan=2, padx=10, pady=6)
        ok = {'go': False}

        def go():
            ok['go'] = True
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.grid(row=3, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text='OK', command=go).pack(side='left', padx=6)
        ttk.Button(bf, text='Abbrechen', command=dlg.destroy).pack(side='left', padx=6)
        dlg.grab_set()
        dlg.wait_window()
        if not ok['go']:
            return
        keys = {'Name': lambda c: (c.name.lower(), c.freq), 'Frequenz': lambda c: (c.freq, c.name.lower()),
                'Betriebsart, Name': lambda c: (c.mode, c.name.lower())}[key.get()]
        if scope.get() == 'Gruppe' and self.gfilter is None:
            messagebox.showinfo('Sortieren', 'Bitte oben zuerst eine Gruppe waehlen.')
            return
        m = self.model
        for g in {c.group for c in self.channels}:
            if scope.get() == 'Gruppe' and g != self.gfilter:
                continue
            grp = sorted((c for c in self.channels if c.group == g), key=keys)
            if len(grp) > m.last - m.first + 1:
                continue
            for i, c in enumerate(grp):
                c.number = m.first + i
        self.persist()

    def clear_group_in_set(self):
        """Alle Speicher einer Gruppe aus dem Satz entfernen (nur PC, nicht das Geraet)."""
        if not self.need_set():
            return
        g = self.gfilter
        if g is None:
            g = simpledialog.askinteger('Gruppe leeren', 'Welche Gruppe im Satz leeren?', parent=self,
                                        minvalue=self.model.group_range[0], maxvalue=self.model.group_range[1])
            if g is None:
                return
        n = sum(1 for c in self.channels if c.group == g)
        if not n:
            messagebox.showinfo('Gruppe leeren', f'Gruppe {self.glabel(g)} ist im Satz schon leer.')
            return
        if messagebox.askyesno('Gruppe leeren', f'Alle {n} Speicher der Gruppe {self.glabel(g)} aus dem Satz loeschen?'):
            self.channels = [c for c in self.channels if c.group != g]
            self.persist()

    def delete_in_radio(self):
        """Speicher oder ganze Gruppen im Funkgeraet loeschen (mit automatischer Sicherung)."""
        key, model = self.dev.get(), self.model
        cfg = self.cfg['devices'][key]
        sel = self.selected_keys()
        keys, groups = None, None
        if sel:
            ans = messagebox.askyesnocancel(
                'Im Geraet loeschen', f'{len(sel)} markierte Speicher im {model.title} loeschen?\n\n'
                                      'Ja = die markierten Speicher\nNein = stattdessen ganze Gruppe(n) waehlen\nAbbrechen = nichts tun')
            if ans is None:
                return
            if ans:
                keys = sorted(sel)
        if keys is None:
            groups = self.ask_groups(model, 'im Geraet loeschen',
                                     str(self.gfilter) if self.gfilter is not None else None)
            if not groups:
                return

        def collect(report):
            r = open_radio(key, cfg)
            try:
                if keys is not None:
                    out = []
                    for i, (g, n) in enumerate(keys, 1):
                        report(f'Pruefe G{g}/{n} ({i}/{len(keys)})', i, len(keys))
                        c = r.read_channel(n, g)
                        if c:
                            out.append(c)
                    return out
                return r.read_all(lambda i, n, g, c: report(f'Lese Gruppe {g}, Speicher {c} ({i}/{n})', i, n), groups)
            finally:
                r.close()

        def found(chans, err):
            if err:
                messagebox.showerror('Loeschen', str(err))
                return
            if not chans:
                messagebox.showinfo('Loeschen', 'Im Geraet sind dort keine belegten Speicher.')
                return
            per = {}
            for c in chans:
                per[c.group] = per.get(c.group, 0) + 1
            summary = ', '.join(f'Gruppe {g}: {n}' for g, n in sorted(per.items()))
            backup = time.strftime(f'Auto-Sicherung vor Loeschen {model.title} %Y-%m-%d %H%M%S')
            if not messagebox.askyesno('Im Geraet loeschen', f'{len(chans)} belegte Speicher im {model.title} werden GELOESCHT '
                                       f'({summary}).\n\nVorher wird eine Sicherung als Satz "{backup}" angelegt. Fortfahren?'):
                return
            store.save_set(key, backup, chans, {g: model.default_label(g) for g in per if model.default_label(g)})

            def erase(report):
                r = open_radio(key, cfg)
                try:
                    for i, c in enumerate(chans, 1):
                        if not report(f'Loesche G{c.group}/{c.number} ({i}/{len(chans)})', i, len(chans)):
                            raise RuntimeError('Abgebrochen - bereits geloeschte Speicher stehen in der Sicherung')
                        r.clear_channel(c.number, c.group)
                finally:
                    r.close()

            def erased(_, err2):
                self.reload_list()
                if err2:
                    messagebox.showerror('Loeschen', str(err2) + f'\n\nSicherung: "{backup}"')
                else:
                    messagebox.showinfo('Loeschen', f'{len(chans)} Speicher im Geraet geloescht.\nSicherung: "{backup}"')

            run_bg(self, 'Im Geraet loeschen', erase, erased)

        run_bg(self, 'Im Geraet loeschen', collect, found)

    def find_repeaters(self):
        if not self.need_set():
            return
        d = RepeaterDialog(self, self)
        if not d.result:
            return
        m, skipped, spilled, added = self.model, 0, set(), 0
        for r in d.result:
            if m.band_groups:                       # IC-9700: Gruppe richtet sich nach dem Band
                g = m.group_for(r.freq)
                n = self.next_free(g) if g is not None else None
            else:                                   # IC-705: aktuelle Gruppe, bei Bedarf die naechsten
                g = start = d.start_group
                n = self.next_free(g)
                while n is None and g < m.group_range[1]:
                    g += 1
                    n = self.next_free(g)
                if n is not None and g != start:
                    spilled.add(g)
            if n is None:
                skipped += 1
                continue
            self.channels.append(repeaters.to_channel(r, n, m, g))
            added += 1
        note = f'{added} Relais uebernommen.'
        if spilled:
            note += f'\n\nDie Start-Gruppe war voll, weitere Relais liegen in Gruppe {", ".join(map(str, sorted(spilled)))}.'
        if skipped:
            note += f'\n\n{skipped} Relais nicht uebernommen (Gruppe voll).'
        self.persist()
        messagebox.showinfo('Relais', note + '\n\nDer Satz ist noch nicht gespeichert (Knopf "Speichern").')

    def settings(self):
        if SettingsDialog(self, self.cfg).ok_pressed:
            store.save_config(self.cfg)

    # -- Geraet
    def ask_groups(self, model, verb='lesen', default=None):
        if default is None:
            default = f'{model.group_range[0]}-{model.group_range[1]}' if model.band_groups else str(model.group)
        txt = simpledialog.askstring(
            'Gruppen', f'Welche Speichergruppen {verb}? (z. B. 1-3 oder 0,2,5-7)\n'
                       f'{model.title}: Gruppen {model.group_range[0]}-{model.group_range[1]}', initialvalue=default, parent=self)
        if not txt:
            return None
        out = set()
        try:
            for part in txt.replace(' ', '').split(','):
                a, _, b = part.partition('-')
                out.update(range(int(a), int(b or a) + 1))
        except ValueError:
            messagebox.showerror('Gruppen', 'Ungueltige Eingabe.')
            return None
        lo, hi = model.group_range
        return sorted(g for g in out if lo <= g <= hi) or None

    def read_radio(self):
        if not self.confirm_discard():
            return
        key, model = self.dev.get(), self.model
        groups = self.ask_groups(model)
        if not groups:
            return
        name = simpledialog.askstring('Vom Geraet lesen', f'Name fuer die Sicherung des {model.title}:',
                                      initialvalue=time.strftime(f'{model.title} %Y-%m-%d %H%M'), parent=self)
        if not name:
            return
        if store.exists(key, name) and not messagebox.askyesno('Sicherung', f'"{name}" existiert. Ersetzen?'):
            return
        cfg = self.cfg['devices'][key]

        def work(report):
            r = open_radio(key, cfg)
            try:
                chans = r.read_all(lambda i, n, g, c: report(f'Lese Gruppe {g}, Speicher {c}  ({i}/{n})', i, n), groups)
                return chans, getattr(r, 'warning', '')
            finally:
                r.close()

        def done(res, err):
            if err:
                messagebox.showerror('Lesen', str(err))
                return
            chans, warn = res
            names = {g: model.default_label(g) for g in groups if model.default_label(g)}
            store.save_set(key, name, chans, names)
            self.refresh_sets(name)
            messagebox.showinfo('Lesen', f'{len(chans)} belegte Speicher aus {len(groups)} Gruppe(n) gelesen und als "{name}" gesichert.'
                                + (f'\n\n{warn}' if warn else ''))

        run_bg(self, 'Vom Geraet lesen', work, done)

    def write_radio(self):
        if not self.need_set():
            return
        key, model = self.dev.get(), self.model
        sel = self.selected_keys()
        chans = [c for c in self.channels if not sel or (c.group, c.number) in sel]
        if not chans:
            return
        bad = [c for c in chans if model.band_of(c.freq) is None or c.mode not in model.modes
               or not model.group_range[0] <= c.group <= model.group_range[1]
               or (model.band_groups and model.group_for(c.freq) != c.group)]
        if bad:
            messagebox.showerror('Schreiben', 'Nicht am ' + model.title + ' moeglich:\n' +
                                 '\n'.join(f'Gruppe {c.group} Kanal {c.number} {c.name} ({fmt_freq(c.freq)} MHz {c.mode})' for c in bad[:15]))
            return
        host = self.cfg['devices'][key]['host']
        if not messagebox.askyesno('Schreiben', f'{len(chans)} Speicher auf {model.title} ({host}) schreiben?\n'
                                   'Bestehende Speicher mit gleicher Nummer werden ueberschrieben.\n'
                                   'Vorher wird automatisch eine Sicherung dieser Kanaele angelegt.'):
            return
        cfg = self.cfg['devices'][key]
        backup_name = time.strftime(f'Auto-Sicherung vor Schreiben {model.title} %Y-%m-%d %H%M%S')

        def work(report):
            r = open_radio(key, cfg)
            try:
                old = []
                for i, c in enumerate(chans, 1):
                    if not report(f'Sichere G{c.group}/{c.number} ({i}/{len(chans)})', i, len(chans) * 2):
                        raise RuntimeError('Abgebrochen')
                    o = r.read_channel(c.number, c.group)
                    if o:
                        old.append(o)
                store.save_set(key, backup_name, old)
                for i, c in enumerate(chans, 1):
                    if not report(f'Schreibe G{c.group}/{c.number} ({i}/{len(chans)})', len(chans) + i, len(chans) * 2):
                        raise RuntimeError('Abgebrochen - bereits geschriebene Kanaele bleiben im Geraet')
                    r.write_channel(c)
                return len(old)
            finally:
                r.close()

        def done(res, err):
            if err:
                messagebox.showerror('Schreiben', str(err))
            else:
                messagebox.showinfo('Schreiben', f'{len(chans)} Speicher geschrieben.\n{res} bisherige Speicher wurden als '
                                    f'"{backup_name}" gesichert.')
            self.reload_list()

        run_bg(self, 'Auf Geraet schreiben', work, done)


if __name__ == '__main__':
    App().mainloop()
