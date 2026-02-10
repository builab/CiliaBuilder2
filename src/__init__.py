# vim: set expandtab shiftwidth=4 softtabstop=4:

from chimerax.core.toolshed import BundleAPI


class _MyAPI(BundleAPI):
    api_version = 1

    @staticmethod
    def start_tool(session, bi, ti, **kw):
        from .tool import start_tool
        return start_tool(session, ti.name)

    @staticmethod
    def register_command(bi, ci, logger):
        from chimerax.core.commands import register
        from . import cmd

        command_name = ci.name
        base_name = command_name.replace(" ", "_")

        func = getattr(cmd, base_name)
        desc = getattr(cmd, base_name + "_desc")

        if desc.synopsis is None:
            desc.synopsis = ci.synopsis

        register(command_name, desc, func)


bundle_api = _MyAPI()
