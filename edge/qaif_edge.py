"""Export-file bridge; no claim of an implemented thermal camera SDK."""
import argparse
import json
import os
import subprocess
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')


def probe():
    devices=[]
    if os.name=='nt':
        query="Get-PnpDevice -PresentOnly | Where-Object { $_.Class -eq 'Camera' -or $_.FriendlyName -match 'thermal|FLIR|TOPDON|InfiRay' } | Select-Object FriendlyName,Class,Status,InstanceId | ConvertTo-Json -Compress"
        result=subprocess.run(['powershell','-NoProfile','-Command',query],capture_output=True,text=True,timeout=25)
        try:
            parsed=json.loads(result.stdout or '[]'); devices=parsed if isinstance(parsed,list) else [parsed]
        except json.JSONDecodeError: pass
    return {'devices':devices,'camera_sdk_verified':False,'raw_temperature_verified':False,
      'note':'Device inventory only. Bring camera model, export format and SDK documentation before enabling capture.'}


def main():
    parser=argparse.ArgumentParser(description='QAIF camera export bridge')
    parser.add_argument('--probe',action='store_true')
    parser.add_argument('--upload-image',type=Path)
    parser.add_argument('--mission')
    parser.add_argument('--mode',choices=['rgb','thermal'],default='rgb')
    parser.add_argument('--source',choices=['uploaded','camera_export','prepared_demo'],default='uploaded')
    parser.add_argument('--server',default='http://127.0.0.1:8765')
    args=parser.parse_args()
    if args.probe:
        print(json.dumps(probe(),ensure_ascii=False,indent=2)); return
    if not args.upload_image or not args.mission: parser.error('Use --probe, or --upload-image PATH --mission ID')
    if not args.server.startswith(('https://','http://127.0.0.1:','http://localhost:')): parser.error('Remote server must use HTTPS')
    name=os.getenv('QAIF_EDGE_USER'); password=os.getenv('QAIF_EDGE_PASSWORD')
    if not name or not password: parser.error('Set QAIF_EDGE_USER and QAIF_EDGE_PASSWORD in local .env')
    with httpx.Client(timeout=40) as client:
        response=client.post(args.server+'/api/auth/login',json={'name':name,'password':password}); response.raise_for_status()
        with args.upload_image.open('rb') as stream:
            response=client.post(args.server+'/api/missions/'+args.mission+'/captures',
              files={'file':(args.upload_image.name,stream)},data={'mode':args.mode,'source':args.source})
        response.raise_for_status()
        print(json.dumps({'capture_id':response.json()['id'],'uploaded':True},indent=2))


if __name__=='__main__': main()
