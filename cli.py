import json, typer
from rich.console import Console
from .manager import code_react_loop
from .mcp.registry import ToolRegistry
from .config import settings
from .container_runner import ContainerPolicy, ContainerError, require_execution_mode

app = typer.Typer()
console = Console()

@app.command()
def run(question: str, model: str = typer.Option(None, help="Override Ollama model"),
        unsafe_exec: bool = typer.Option(False, '--unsafe-exec', help="Run trusted generated code with host privileges. NOT a sandbox."),
        container_image: str = typer.Option(None, '--container-image', help="Approved local sha256 image ID for contained stdlib execution.")):
    try:
        policy = ContainerPolicy(container_image) if container_image is not None else None
        if policy is not None:
            require_execution_mode(unsafe_exec, policy)
        if unsafe_exec:
            console.print('[yellow]Unsafe host execution enabled for this command.[/yellow]')
        res = code_react_loop(question, model=model, allow_unsafe_execution=unsafe_exec, container=policy)
    except (PermissionError, ValueError, ContainerError) as error:
        console.print(str(error))
        raise typer.Exit(code=2)
    console.rule("[bold green]Final Answer")
    console.print(res["answer"])

@app.command("tools")
def list_tools():
    reg = ToolRegistry()
    tools = reg.list()
    console.print_json(data=tools)

@app.command("tool-run")
def tool_run(name: str, args: str = typer.Option("{}", help="JSON string for arguments"),
             unsafe_exec: bool = typer.Option(False, '--unsafe-exec', help="Allow trusted code to run with host privileges. NOT a sandbox."),
             container_image: str = typer.Option(None, '--container-image', help="Approved local sha256 image ID for contained stdlib execution.")):
    try:
        policy = ContainerPolicy(container_image) if container_image is not None else None
        require_execution_mode(unsafe_exec, policy)
        reg = ToolRegistry()
        res = reg.run(name, json.loads(args), allow_unsafe_execution=unsafe_exec, container=policy)
    except (PermissionError, ValueError, ContainerError) as error:
        console.print(str(error))
        raise typer.Exit(code=2)
    console.print(res)

if __name__ == "__main__":
    app()
