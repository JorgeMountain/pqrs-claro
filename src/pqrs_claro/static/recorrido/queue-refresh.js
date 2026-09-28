// Refresh only a visible inbox with active work; never starts a job.
export function createQueueRefresh({load,visible,hasWork,editing=()=>false,setTimer=setTimeout,clearTimer=clearTimeout}){
  let timer,failures=0;
  function stop(){clearTimer(timer);timer=null;}
  function schedule(failed=false){
    stop();failures=failed?failures+1:0;
    if(!visible()||(!failed&&!hasWork()))return;
    timer=setTimer(async()=>{
      timer=null;if(!visible())return;
      if(editing()){schedule(failed);return;}
      await load(true);
    },failed?Math.min(30000,2000*2**Math.min(failures,4)):2000);
  }
  return {schedule,stop};
}
