from bitbang import BitBangASGI
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/favicon.ico")
async def favicon():    
    return FileResponse('static/favicon.png', media_type='image/png')

@app.get("/", response_class=HTMLResponse)
async def index():
    with open('index.html') as f:
        return f.read()


if __name__ == '__main__':
    adapter = BitBangASGI(app, program_name='simple_fastapi')
    adapter.run()
