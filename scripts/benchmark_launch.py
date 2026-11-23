"""Run from the repository root with psutil installed. Optional argument: driver count."""

import asyncio,sys,json,time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import psutil
sys.path.insert(0,str(Path.cwd()))
from profile_manager.browser_service import BrowserService
from profile_manager.profile_store import ProfileStore

async def main(root):
    store=ProfileStore(root/'app',root/'profiles')
    profiles=[store.create_profile(f'Benchmark {i}') for i in range(20)]
    service=BrowserService(lambda *_:None, playwright_instances=int(sys.argv[1]) if len(sys.argv)>1 else 1)
    loop=asyncio.get_running_loop()
    lag=[]
    seen={}
    peaks=[0,0]
    def sample():
        processes=psutil.Process().children(recursive=True)
        rss=0
        for p in processes:
            try:
                seen[p.pid,p.create_time()]=p
                rss+=p.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        peaks[0]=max(peaks[0],len(processes))
        peaks[1]=max(peaks[1],rss)
    async def monitor():
        while True:
            start=loop.time()
            await asyncio.sleep(.05)
            lag.append(max(0,loop.time()-start-.05))
            await asyncio.to_thread(sample)
    def verify(url):
        with urlopen(url+'/json/version',timeout=5) as response:
            return json.load(response)['webSocketDebuggerUrl']
    async def launch(profile):
        start=loop.time()
        try:
            url=await service.open(profile)
            latency=loop.time()-start
            await asyncio.to_thread(verify,url)
            return {'id':profile.id,'seconds':latency,'cdp':url}
        except Exception as exc:
            return {'id':profile.id,'seconds':loop.time()-start,'error':str(exc)[:350]}
    watcher=asyncio.create_task(monitor())
    start=loop.time()
    try:
        rows=await asyncio.gather(*(launch(p) for p in profiles))
        wall=loop.time()-start
        counts=service.counts()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher,return_exceptions=True)
        await service.close_all()
    await asyncio.to_thread(psutil.wait_procs,list(seen.values()),3)
    survivors=[p.pid for p in seen.values() if p.is_running()]
    print(json.dumps(dict(wall=wall, failures=sum('error' in r for r in rows), rows=rows, counts=counts, peak_processes=peaks[0],peak_rss=peaks[1],max_lag=max(lag,default=0),survivors=survivors)))
    return bool(survivors or any('error' in r for r in rows))

if __name__=='__main__':
    Path('.profile-manager').mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='benchmark-',dir='.profile-manager') as directory:
        failed=asyncio.run(main(Path(directory).resolve()))
    sys.exit(failed)
