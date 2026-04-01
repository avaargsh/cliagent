"""Replay commands."""

from __future__ import annotations


def register(subparsers) -> None:
    parser = subparsers.add_parser("replay", help="Replay execution events.")
    replay_subparsers = parser.add_subparsers(dest="replay_action")

    run_parser = replay_subparsers.add_parser("run", help="Replay a work order.")
    run_parser.add_argument("work_order_id")
    run_parser.set_defaults(handler=handle_run, command_name="replay run")


def handle_run(args, context):
    return context.queries.run_replay(args.work_order_id)
