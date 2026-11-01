/* Exact baseline expectation for a symmetric +/-1 walk, not invented samples. */
(function(root){
'use strict';
function randomAbsoluteError(roundCount,actualDelta){
 if(!Number.isInteger(roundCount)||roundCount<0||roundCount>10000||!Number.isFinite(actualDelta))throw Error('Invalid random baseline input');
 if(roundCount===0)return Math.abs(actualDelta);
 // Normalize relative binomial weights from their mode to avoid underflow.
 const mode=Math.floor(roundCount/2);let total=1,error=Math.abs(2*mode-roundCount-actualDelta),weight=1;
 for(let k=mode;k<roundCount;k++){weight*=((roundCount-k)/(k+1));total+=weight;error+=weight*Math.abs(2*(k+1)-roundCount-actualDelta);}
 weight=1;
 for(let k=mode;k>0;k--){weight*=k/(roundCount-k+1);total+=weight;error+=weight*Math.abs(2*(k-1)-roundCount-actualDelta);}
 return error/total;
}
const api={randomAbsoluteError};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.KronosResearch=api;
})(typeof window!=='undefined'?window:this);
