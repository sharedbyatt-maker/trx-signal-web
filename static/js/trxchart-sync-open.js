'use strict';
const bridgeCode=new URL(location.href).searchParams.get('bridge')||'';
if(/^[a-f0-9]{48}$/.test(bridgeCode))location.replace('/admin/trxchart-sync?bridge='+bridgeCode);
