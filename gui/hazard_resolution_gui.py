#!/usr/bin/env python3
"""
GUI for choosing hazard resolution strategies.

Provides an interactive dialog for users to choose between stalling
and bypassing for each detected pipeline hazard.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import List, Callable
from opt.pipeline.hazard_resolution import DetectedHazard, HazardResolutionStrategy


class HazardResolutionDialog:
    """Dialog for choosing hazard resolution strategies."""

    def __init__(self, parent, hazards: List[DetectedHazard],
                 on_apply: Callable[[List[DetectedHazard]], None]):
        """
        Create hazard resolution dialog.

        Args:
            parent: Parent Tk window
            hazards: List of detected hazards
            on_apply: Callback function called when user clicks Apply
        """
        self.parent = parent
        self.hazards = hazards
        self.on_apply_callback = on_apply
        self.strategy_vars = []  # Store StringVar for each hazard's strategy choice

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Hazard Resolution Strategy Selection")
        self.dialog.geometry("1000x700")

        self._create_widgets()

    def _create_widgets(self):
        """Create all GUI widgets."""
        # Title
        title_frame = tk.Frame(self.dialog)
        title_frame.pack(fill=tk.X, padx=10, pady=10)

        title_label = tk.Label(
            title_frame,
            text=f"Choose Resolution Strategy for {len(self.hazards)} Detected Hazards",
            font=("Arial", 14, "bold")
        )
        title_label.pack()

        subtitle_label = tk.Label(
            title_frame,
            text="Select 'Stall' to insert stall logic, 'Bypass' to forward values, or 'None' to skip",
            font=("Arial", 10)
        )
        subtitle_label.pack()

        # Bulk action buttons
        bulk_frame = tk.Frame(self.dialog)
        bulk_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(bulk_frame, text="Set all to:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)

        tk.Button(
            bulk_frame,
            text="All Stall",
            command=lambda: self._set_all_strategies(HazardResolutionStrategy.STALL)
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            bulk_frame,
            text="All Bypass",
            command=lambda: self._set_all_strategies(HazardResolutionStrategy.BYPASS)
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            bulk_frame,
            text="All None",
            command=lambda: self._set_all_strategies(HazardResolutionStrategy.NONE)
        ).pack(side=tk.LEFT, padx=2)

        # Main content area with scrollbar
        content_frame = tk.Frame(self.dialog)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Create canvas and scrollbar
        canvas = tk.Canvas(content_frame, bg='white')
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Create hazard entry for each detected hazard
        for i, hazard in enumerate(self.hazards):
            self._create_hazard_entry(scrollable_frame, hazard, i)

        # Button frame
        button_frame = tk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(
            button_frame,
            text="Cancel",
            command=self.dialog.destroy,
            width=15
        ).pack(side=tk.RIGHT, padx=5)

        tk.Button(
            button_frame,
            text="Apply",
            command=self._on_apply,
            width=15,
            bg="#4CAF50",
            fg="white"
        ).pack(side=tk.RIGHT, padx=5)

    def _create_hazard_entry(self, parent, hazard: DetectedHazard, index: int):
        """Create a GUI entry for a single hazard."""
        # Create frame for this hazard
        hazard_frame = tk.LabelFrame(
            parent,
            text=f"Hazard {index + 1}",
            bg='white',
            padx=10,
            pady=10
        )
        hazard_frame.pack(fill=tk.X, padx=5, pady=5)

        # Hazard description
        if hazard.is_indexed:
            desc_text = (
                f"{hazard.hazard_type} Hazard: "
                f"{hazard.write_stage_name} writes {hazard.resource}[{hazard.write_index_name}], "
                f"{hazard.read_stage_name} reads {hazard.resource}[{hazard.read_index_name}]"
            )
        else:
            desc_text = (
                f"{hazard.hazard_type} Hazard on {hazard.resource}: "
                f"write@{hazard.write_stage_name}, read@{hazard.read_stage_name}"
            )

        tk.Label(
            hazard_frame,
            text=desc_text,
            font=("Arial", 10),
            bg='white',
            anchor='w'
        ).pack(fill=tk.X)

        # Forwarding distance info
        distance = hazard.get_forwarding_distance()
        distance_text = f"Forwarding distance: {distance} stage(s)"
        if distance > 2:
            distance_text += " (long forwarding path)"

        tk.Label(
            hazard_frame,
            text=distance_text,
            font=("Arial", 9, "italic"),
            bg='white',
            fg='#666',
            anchor='w'
        ).pack(fill=tk.X)

        # Strategy selection
        strategy_frame = tk.Frame(hazard_frame, bg='white')
        strategy_frame.pack(fill=tk.X, pady=5)

        tk.Label(
            strategy_frame,
            text="Resolution:",
            font=("Arial", 10, "bold"),
            bg='white'
        ).pack(side=tk.LEFT, padx=5)

        strategy_var = tk.StringVar(value=HazardResolutionStrategy.STALL.value)
        self.strategy_vars.append(strategy_var)

        # Radio buttons for strategy choice
        for strategy in [HazardResolutionStrategy.STALL,
                        HazardResolutionStrategy.BYPASS,
                        HazardResolutionStrategy.NONE]:
            tk.Radiobutton(
                strategy_frame,
                text=strategy.value.capitalize(),
                variable=strategy_var,
                value=strategy.value,
                bg='white'
            ).pack(side=tk.LEFT, padx=5)

        # Add description of each option
        descriptions = {
            HazardResolutionStrategy.STALL: "Stall earlier stage until hazard clears",
            HazardResolutionStrategy.BYPASS: "Forward value from later stage to earlier stage",
            HazardResolutionStrategy.NONE: "No automatic resolution (manual handling required)"
        }

        desc_label = tk.Label(
            hazard_frame,
            text="",
            font=("Arial", 9, "italic"),
            bg='white',
            fg='#666',
            wraplength=800,
            justify=tk.LEFT
        )
        desc_label.pack(fill=tk.X, padx=5)

        def update_description(*args):
            current = strategy_var.get()
            for strat, desc in descriptions.items():
                if strat.value == current:
                    desc_label.config(text=desc)
                    break

        strategy_var.trace('w', update_description)
        update_description()  # Set initial description

    def _set_all_strategies(self, strategy: HazardResolutionStrategy):
        """Set all hazards to the same strategy."""
        for var in self.strategy_vars:
            var.set(strategy.value)

    def _on_apply(self):
        """Apply button handler."""
        # Update hazard resolution strategies
        for i, hazard in enumerate(self.hazards):
            strategy_str = self.strategy_vars[i].get()
            hazard.resolution = HazardResolutionStrategy(strategy_str)

        # Show summary
        summary = self._generate_summary()
        if messagebox.askyesno(
            "Confirm Resolution Strategies",
            f"Apply the following resolution strategies?\n\n{summary}"
        ):
            # Call the callback
            self.on_apply_callback(self.hazards)
            self.dialog.destroy()

    def _generate_summary(self) -> str:
        """Generate a summary of chosen strategies."""
        stall_count = sum(1 for h in self.hazards if h.resolution == HazardResolutionStrategy.STALL)
        bypass_count = sum(1 for h in self.hazards if h.resolution == HazardResolutionStrategy.BYPASS)
        none_count = sum(1 for h in self.hazards if h.resolution == HazardResolutionStrategy.NONE)

        summary = f"Stall: {stall_count}\n"
        summary += f"Bypass: {bypass_count}\n"
        summary += f"None: {none_count}\n"
        summary += f"\nTotal: {len(self.hazards)} hazards"

        return summary


def show_hazard_resolution_dialog(parent, hazards: List[DetectedHazard],
                                  on_apply: Callable[[List[DetectedHazard]], None]):
    """
    Show the hazard resolution dialog.

    Args:
        parent: Parent Tk window
        hazards: List of detected hazards
        on_apply: Callback function called when user clicks Apply
    """
    dialog = HazardResolutionDialog(parent, hazards, on_apply)
    dialog.dialog.wait_window()  # Make it modal
