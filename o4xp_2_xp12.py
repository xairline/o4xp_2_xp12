
# MIT License

# Copyright (c) 2023 Holger Teutsch

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys, os, os.path, time, shlex, subprocess, shutil, re, threading
from queue import Queue, Empty
import configparser
import logging

log = logging.getLogger("o4x_2_xp12")

XP12root = "E:\\X-Plane-12"
dsf_tool = "E:\\XPL-Tools\\xptools_win_23-4\\tools\\DSFtool"
cmd_7zip = "c:\\Program Files\\7-Zip\\7z.exe"

work_dir = "work"

class Dsf():
    is_converted = False

    def __init__(self, fname):
        self.fname = fname.replace('\\', '/')
        self.fname_bck = self.fname + "-pre_o4xp_2_xp12"
        self.cnv_marker = self.fname + "-o4xp_2_xp12_done"
        self.dsf_base, _ = os.path.splitext(os.path.basename(self.fname))
        self.rdata_fn = os.path.join(work_dir, self.dsf_base + ".rdata")
        self.rdata = []
        if os.path.isfile(self.cnv_marker):
            self.is_converted = True

    def __repr__(self):
        return f"{self.fname}"

    def run_cmd(self, cmd):
        out = subprocess.run(shlex.split(cmd), capture_output = True, shell = True)
        if out.returncode != 0:
            log.error(f"Can't run {cmd}: {out}")
            return False

        return True

    def convert(self):
        i = self.fname.find("/Earth nav data/")
        assert i > 0, "invalid filename"

        # check for already extracted raster data
        if os.path.isfile(self.rdata_fn):
            self.rdata = open(self.rdata_fn, "r").readlines()
        else:
            xp12_dsf = XP12root + "/Global Scenery/X-Plane 12 Global Scenery" + self.fname[i:]
            xp12_dsf_txt = os.path.join(work_dir, self.dsf_base + ".txt-xp12")
            #print(xp12_dsf)
            #print(xp12_dsf_txt)
            if not self.run_cmd(f'"{dsf_tool}" -dsf2text "{xp12_dsf}" "{xp12_dsf_txt}"'):
                return False

            with open(self.rdata_fn, "w") as frd:
                with open(xp12_dsf_txt, "r") as dsft:
                    for l in dsft.readlines():
                        if l.find("RASTER_") == 0:
                            self.rdata.append(l)
                            #print(l.rstrip())
                            frd.write(l)

            os.remove(xp12_dsf_txt)

        # always create a backup
        if not os.path.isfile(self.fname_bck):
            shutil.copy2(self.fname, self.fname_bck)

        o4xp_dsf = self.fname_bck
        o4xp_dsf_txt = os.path.join(work_dir, self.dsf_base + ".txt-o4xp")
        if not self.run_cmd(f'"{dsf_tool}" -dsf2text "{o4xp_dsf}" "{o4xp_dsf_txt}"'):
            return False

        with open(o4xp_dsf_txt, 'a') as f:
            for l in self.rdata:
                if (l.find("spr") > 0 or l.find("sum") > 0 or l.find("win") > 0 # use a positive list
                   or l.find("fal") > 0 or l.find("soundscape") > 0 or l.find("elevation") > 0):
                    f.write(l)

        fname_new = self.fname + "-new"
        fname_new_1 = fname_new + "-1"
        if not self.run_cmd(f'"{dsf_tool}" -text2dsf "{o4xp_dsf_txt}" "{fname_new_1}"'):
            return False

        if not self.run_cmd(f'"{cmd_7zip}" a -t7z -m0=lzma "{fname_new}" "{fname_new_1}"'):
            return False

        os.remove(fname_new_1)
        os.remove(self.fname)
        os.rename(fname_new, self.fname)
        open(self.cnv_marker, "w")  # create the marker
        return True

class DsfList():
    _lat_lon_re = None
    _o4xp_re = re.compile('zOrtho4XP_.*')
    _ao_re = re.compile('z_autoortho.scenery.z_ao_[a-z]+')

    def __init__(self, xp12root):
        self.xp12root = xp12root
        self.queue = Queue()
        self.custom_scenery = os.path.normpath(os.path.join(XP12root, "Custom Scenery"))
        self._threads = []

    def set_rect(self, lat1, lon1, lat2, lon2):
        self._lat1 = lat1
        self._lon1 = lon1
        self._lat2 = lat2
        self._lon2 = lon2
        self._lat_lon_re = re.compile('([+-]\d\d)([+-]\d\d\d).dsf')

    def scan(self):
        for dir, dirs, files in os.walk(self.custom_scenery):
            if not self._o4xp_re.search(dir) and  not self._ao_re.search(dir):
                continue
            for f in files:
                _, ext = os.path.splitext(f)
                if ext != '.dsf':
                    continue

                if self._lat_lon_re is not None:
                    m = self._lat_lon_re.match(f.replace('\\', '/'))
                    assert m is not None
                    lat = int(m.group(1))
                    lon = int(m.group(2))
                    if (lat < self._lat1 or lon < self._lon1 or
                        lat > self._lat2 or lon > self._lon2):
                        continue

                dsf = Dsf(os.path.join(dir, f))
                if not dsf.is_converted:
                    self.queue.put(dsf)
                    log.info(f"queued {dsf}")

    def worker(self, i):
         while True:
            try:
                dsf = self.queue.get(block = False, timeout = 5)    # timeout to make it interruptible
            except Empty:
                break

            log.info(f"{i} -> S -> {dsf}")

            try:
                dsf.convert()
            except Exception as err:
                log.warning({err})

            log.info(f"{i} -> E -> {dsf}")

    def convert(self, num_workers):
        qlen_start = self.queue.qsize()
        start_time = time.time()

        for i in range(num_workers):
            t = threading.Thread(target=self.worker, args=(i,), daemon = True)
            self._threads.append(t)
            t.start()

        while True:
            qlen = self.queue.qsize()
            if qlen == 0:
                break
            log.info(f"{qlen_start - qlen}/{qlen_start} = {100 * (1-qlen/qlen_start):0.1f}% processed")
            time.sleep(20)

        for t in self._threads:
            t.join()

        end_time = time.time()
        log.info(f"Processed {qlen_start} tiles in {end_time - start_time:0.1f} seconds")

###########
## main
###########
logging.basicConfig(level=logging.INFO,
                    handlers=[logging.FileHandler(filename = "o4x_2_xp12.log", mode='w'),
                              logging.StreamHandler()])

#log.info(f"Version: {version}")
CFG = configparser.ConfigParser()
CFG.read('o4xp_2_xp12.ini')

log.info(f"args: {sys.argv}")

dsf_list = DsfList(XP12root)

i = 1
while i < len(sys.argv):
    if sys.argv[i] == "-root":
        i = i + 1
        if i >= len(sys.argv):
            log.error('No argument after "-root"')
            exit(1)
        XP12root = sys.argv[i]
    elif sys.argv[i] == "-rect":
        i = i + 1
        if i >= len(sys.argv):
            log.error('No argument after "-rect"')
            exit(1)

        m = re.match("([+-]\d\d)([+-]\d\d\d),([+-]\d\d)([+-]\d\d\d)", sys.argv[i])
        if m is None:
            log.error('invalid argument to "-rect", should be like +50+008,+51+009')
            exit(1)

        lat1 = int(m.group(1))
        lon1 = int(m.group(2))
        lat2 = int(m.group(3))
        lon2 = int(m.group(4))
        log.info(f"restricting to rect ({lat1},{lon1}) -> ({lat2},{lon2})")
        dsf_list.set_rect(lat1, lon1, lat2, lon2)

    i = i + 1

if not os.path.isdir(work_dir):
    os.makedirs(work_dir)

dsf_list.scan()
#dsf_list.queue.put(Dsf("E:/X-Plane-12/Custom Scenery/z_autoortho/scenery/z_ao_eur/Earth nav data/+50+000/+51+009.dsf"))

dsf_list.convert(10)
