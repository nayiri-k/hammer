#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  hammer-vlsi plugin for Cadence Joules.
#
#  See LICENSE for licence details.

import shutil
from typing import List, Dict, Optional, Tuple

import os
import errno
from textwrap import dedent
from datetime import datetime
from pathlib import Path
import pandas as pd

from hammer.vlsi import HammerPowerTool, HammerToolStep, HammerToolHookAction, HammerTool, \
                        MMMCCornerType, FlowLevel, PowerReport
from hammer.logging import HammerVLSILogging

from hammer.common.cadence import CadenceTool

from .parsing import PowerParser

class Joules(HammerPowerTool, CadenceTool):

    @property
    def post_synth_sdc(self) -> Optional[str]:
        return None

    def tool_config_prefix(self) -> str:
        return "power.joules"

    @property
    def env_vars(self) -> Dict[str, str]:
        new_dict = dict(super().env_vars)
        new_dict["JOULES_BIN"] = self.get_setting("power.joules.joules_bin")
        return new_dict
    
    @property
    def generated_scripts_dir(self) -> str:
        return os.path.join(self.run_dir, "generated-scripts")

    @property
    def load_power_script(self) -> str:
        return os.path.join(self.generated_scripts_dir, "load_power")
    
    @property
    def load_power_tcl(self) -> str:
        return self.load_power_script + ".tcl"

    @property
    def _step_transitions(self) -> List[Tuple[str, str]]:
        """
        Private helper property to keep track of which steps we ran so that we
        can create symlinks.
        This is a list of (pre, post) steps
        """
        return self.attr_getter("__step_transitions", [])

    @_step_transitions.setter
    def _step_transitions(self, value: List[Tuple[str, str]]) -> None:
        self.attr_setter("__step_transitions", value)

    def do_pre_steps(self, first_step: HammerToolStep) -> bool:
        assert super().do_pre_steps(first_step)
        # Restore from the last checkpoint if we're not starting over.
        if first_step != self.first_step:
            self.block_append("read_db pre_{step}".format(step=first_step.name))
            # NOTE: reading stimulus from this sdb file just errors out, unsure why
            # if os.path.exists(self.sdb_path):
            #     self.block_append(f"read_stimulus -format sdb -file {self.sdb_path}")
        return True

    def do_between_steps(self, prev: HammerToolStep, next: HammerToolStep) -> bool:
        assert super().do_between_steps(prev, next)
        # Write a checkpoint to disk.
        self.block_append("write_db -all_root_attributes -to_file pre_{step}".format(step=next.name))
        # Symlink the database to latest for load_power script later.
        self.block_append("ln -sfn pre_{step} latest".format(step=next.name))
        self._step_transitions = self._step_transitions + [(prev.name, next.name)]
        return True

    def do_post_steps(self) -> bool:
        assert super().do_post_steps()
        # Create symlinks for post_<step> to pre_<step+1> to improve usability.
        try:
            for prev, next in self._step_transitions:
                os.symlink(
                    os.path.join(self.run_dir, "pre_{next}".format(next=next)), # src
                    os.path.join(self.run_dir, "post_{prev}".format(prev=prev)) # dst
                )
        except OSError as e:
            if e.errno != errno.EEXIST:
                self.logger.warning("Failed to create post_* symlinks: " + str(e))

        # Create db post_<last step>
        # TODO: this doesn't work if you're only running the very last step
        if len(self._step_transitions) > 0:
            last = "post_{step}".format(step=self._step_transitions[-1][1])
            self.block_append("write_db -to_file {last}".format(last=last))
            # Symlink the database to latest for load_power script later.
            self.block_append("ln -sfn {last} latest".format(last=last))

        return self.run_joules()
    
    def get_tool_hooks(self) -> List[HammerToolHookAction]:
        return [self.make_persistent_hook(joules_global_settings)]

    @property
    def steps(self) -> List[HammerToolStep]:
        return self.make_steps_from_methods([
            self.init_design,
            self.synthesize_design,
            self.report_power,
        ])

    def check_level(self) -> bool:
        if self.level == FlowLevel.RTL or self.level == FlowLevel.SYN:
            return True
        else:
            self.logger.error("The FlowLevel is invalid. The Joules plugin only supports RTL and post-synthesis analysis. Check your power tool setting and flow step.")
            return False

    def init_technology(self) -> bool:
        # libs, define RAMs, define corners
        block_append = self.block_append

        corners = self.get_mmmc_corners()
        if MMMCCornerType.Extra in list(map(lambda corner: corner.type, corners)):
            for corner in corners:
                if corner.type is MMMCCornerType.Extra:
                    block_append("read_libs {EXTRA_LIBS} -domain extra -infer_memory_cells".format(EXTRA_LIBS=self.get_timing_libs(corner)))
                    break
        elif MMMCCornerType.Setup in list(map(lambda corner: corner.type, corners)):
            for corner in corners:
                if corner.type is MMMCCornerType.Setup:
                    block_append("read_libs {SETUP_LIBS} -domain setup -infer_memory_cells".format(SETUP_LIBS=self.get_timing_libs(corner)))
                    break
        elif MMMCCornerType.Hold in list(map(lambda corner: corner.type, corners)):
            for corner in corners:
                if corner.type is MMMCCornerType.Hold:
                    block_append("read_libs {HOLD_LIBS} -domain hold -infer_memory_cells".format(HOLD_LIBS=self.get_timing_libs(corner)))
                    break
        else:
            self.logger.error("No corners found")
            return False
        return True

    def init_design(self) -> bool:
        if not self.check_level(): return False
        if not self.init_technology(): return False
        block_append = self.block_append

        top_module = self.get_setting("power.inputs.top_module")
        # Replace . to / formatting in case argument passed from sim tool
        tb_dut = self.tb_dut.replace(".", "/")

        defines = self.get_setting("power.inputs.defines",[])
        defines_str = " ".join(["-define "+d for d in defines])

        if self.level == FlowLevel.RTL:
            # We are switching working directories and Joules still needs to find paths.
            abspath_input_files = list(map(lambda name: os.path.join(os.getcwd(), name), self.input_files))  # type: List[str]
            # Read in the design files
            block_append("""read_hdl {DEFINES} -sv {FILES}""".format(
                DEFINES=defines_str,
                FILES=" ".join(abspath_input_files)))

        # Setup the power specification
        power_spec_arg = self.map_power_spec_name()
        power_spec_file = self.create_power_spec()
        if not power_spec_arg or not power_spec_file:
            return False

        block_append("read_power_intent -{tpe} {spec} -module {TOP_MODULE}".format(tpe=power_spec_arg, spec=power_spec_file, TOP_MODULE=top_module))

        # Set options pre-elaboration
        block_append("set_db leakage_power_effort medium")
        block_append("set_db lp_insert_clock_gating true")

        if self.level == FlowLevel.RTL:
            # Elaborate the design
            block_append("elaborate {TOP_MODULE}".format(TOP_MODULE=top_module))
        elif self.level == FlowLevel.SYN:
            # Read in the synthesized netlist
            block_append("read_netlist {DEFINES} {FILES}".format(
                DEFINES=defines_str,
                FILES=" ".join(self.input_files)))

            # Read in the post-synth SDCs
            block_append("read_sdc {}".format(self.sdc))
        
        block_append("apply_power_intent")
        block_append("commit_power_intent")
        
        return True


    def synthesize_design(self) -> bool:
        block_append = self.block_append

        if self.level == FlowLevel.RTL:
            # Generate and read the SDCs
            sdc_files = self.generate_sdc_files()  # type: List[str]
            block_append("read_sdc {}".format(" ".join(sdc_files)))
            block_append("syn_power -effort medium")

        return True


    @property
    def all_stim_cmds(self) -> List[str]:
        """
        Private helper property to keep track of which stimulus commands have already been run
        """
        return self.attr_getter("__all_stim_cmds", [])
    @all_stim_cmds.setter
    def all_stim_cmds(self, value: List[str]) -> None:
        self.attr_setter("__all_stim_cmds", value)

    def generate_alias(self, read_stim_cmd) -> Tuple[str, bool]:
        """
        Return Tuple(
            stim alias,
            whether we already ran read_stimulus for this waveform
        )
        """
        new_stim = not (read_stim_cmd in self.all_stim_cmds)
        if new_stim:
            alias = len(self.all_stim_cmds)
            self.all_stim_cmds = self.all_stim_cmds + [read_stim_cmd]
        else:
            alias = self.all_stim_cmds.index(read_stim_cmd)
        return f"stim{alias}", new_stim

    
    def configs_to_cmds(self):
        tb_dut = self.tb_dut.replace(".", "/")
        power_report_configs = []
        saifs = self.get_setting("power.inputs.saifs")
        # create power report config for each waveform/SAIF file
        for sim_file in self.waveforms + saifs:
            power_report_configs.append(
                PowerReport(
                    waveform_path=sim_file,
                    inst=None, module=None,
                    levels=None,
                    start_time=None, end_time=None,
                    interval_list=None,
                    interval_size=None,
                    toggle_signal=None, num_toggles=None,
                    frame_count=None,
                    power_type=None,
                    report_stem=None,
                    output_formats=['report'],
                    tcl_cmd=None,tcl_args=None,
                    ))
        power_report_configs += self.get_power_report_configs() # append report configs from yaml file

        all_power_report_cfgs = []
        for report in power_report_configs:
            cfg = {}
            abspath_waveform = os.path.join(os.getcwd(), report.waveform_path)
            read_stim_cmd = f"read_stimulus -file {abspath_waveform} -dut_instance {self.tb_name}/{tb_dut}"

            if report.start_time:
                read_stim_cmd += f" -start {report.start_time.value_in_units('ns')}ns"
            if report.end_time:
                read_stim_cmd += f" -end {report.end_time.value_in_units('ns')}ns"

            # Time-based analysis
            time_based_cfgs = [report.interval_size, report.interval_list, report.num_toggles, report.frame_count]
            time_based_cfgs = [(val is not None) for val in time_based_cfgs]
            time_based_analysis = any(time_based_cfgs)
            if sum(time_based_cfgs) > 1:
                self.logger.warning("More than one time-based analysis specified, using first one in {interval_size, interval_list, toggle_signal/num_toggles, frame_count}")
    
            if report.interval_size:
                read_stim_cmd += f" -interval_size {report.interval_size.value_in_units('ns')}ns"
            elif report.interval_list:
                read_stim_cmd += f" -interval_list {report.interval_list}"
            elif report.num_toggles:
                toggle_signal = report.toggle_signal
                if toggle_signal is None:
                    toggle_signal = self.get_clock_ports()[0]
                    self.logger.warning(f"Unspecified toggle_signal for num_toggles, using {toggle_signal} signal")
                read_stim_cmd += f" -cycles {report.num_toggles} {toggle_signal}"
            elif report.frame_count:
                read_stim_cmd += f" -frame_count {report.frame_count}"

            # Read stimulus + compute power
            stim_alias, new_stim = self.generate_alias(read_stim_cmd)
            cfg['read_stim_cmd'] = ""
            if new_stim:
                cfg['read_stim_cmd'] = f"{read_stim_cmd} -alias {stim_alias} -append"
                # block_append(f"write_sdb -out {alias}.sdb") # NOTE: subsequent read_sdb command errors when reading this file back in, so don't cache for now
                mode = "time_based" if time_based_analysis else "average"
                cfg['compute_power_cmd'] = f"compute_power -mode {mode} -stim {stim_alias} -append"

            inst_str = f"-inst {report.inst}" if report.inst is not None else ""
            module_str = f"-module {report.module}" if report.module is not None else ""
            levels_str = f"-levels {report.levels}" if report.levels is not None else ""
            type_str = f"-types {report.power_type}" if report.power_type is not None else "-types total"
            if report.output_formats is None:
                output_formats = {'report'} if report.tcl_args is None else set()
            else:
                output_formats = set(report.output_formats)
            tcl_args = report.tcl_args if report.tcl_args is not None else ""

            report_stem = os.path.basename(report.waveform_path) if report.report_stem is None else report.report_stem

            if not report_stem.startswith('/'):  # get absolute path
                save_dir = Path(self.run_dir)/"reports"
                save_dir.mkdir(exist_ok=True,parents=True)
                report_stem = str(save_dir/report_stem)

            # NOTE: for parsing power reports, we assume last argument in each cmd is the output filepath
            cmds = []

            # write out start/end times for frames analyzed
            #   NOTE: Joules manual says times are written out in ns, but they are actually written in s
            cfg['read_stim_cmd'] += f"\ndump_frame_info {stim_alias} {report_stem}"

            # use set intersection to determine whether two lists have at least one element in common
            if {'report','all'} & output_formats:
                h_levels_str = "-levels all" if levels_str == "" else levels_str
                cmds.append(f"report_power -stims {stim_alias} {inst_str} {module_str} {levels_str} -unit mW {tcl_args} -out {report_stem}.power.rpt")
                cmds.append(f"report_power -stims {stim_alias} {inst_str} {module_str} {levels_str} -by_hierarchy {h_levels_str} -unit mW {tcl_args} -out {report_stem}.hier.power.rpt")
            if {'activity','all'} & output_formats:
                cmds.append(f"report_activity -stims {stim_alias} {inst_str} {module_str} {levels_str} {tcl_args} -out {report_stem}.activity.rpt")
                cmds.append(f"report_activity -stims {stim_alias} -by_hierarchy {levels_str} {tcl_args} -out {report_stem}.hier.activity.rpt")
            if {'ppa','all'} & output_formats:
                root_str = inst_str.replace('-inst','-root')
                cmds.append(f"report_ppa {root_str} {module_str} {tcl_args} > {report_stem}.ppa.rpt")
            if {'area','all'} & output_formats:
                cmds.append(f"report_area > {report_stem}.area.rpt")
            if {'plot_profile','profile','all'} & output_formats:
                if not time_based_analysis:
                    self.logger.error("Must specify either interval_size or toggle_signal+num_toggles in power.inputs.report_configs to generate plot_profile report (frame-based analysis).")
                    return False
                # NOTE: we don't include levels_str here bc category is total power anyways
                cmds.append(f"plot_power_profile -stims {stim_alias} {inst_str} {module_str} {levels_str} -by_category {{total}} {type_str} -unit mW -format png {tcl_args} -out {report_stem}.profile.png")
            if {'write_profile','profile','all'} & output_formats:
                if not time_based_analysis:
                    self.logger.error("Must specify either interval_size or toggle_signal+num_toggles in power.inputs.report_configs to generate write_profile report (frame-based analysis).")
                    return False
                root_str = inst_str.replace('-inst','-root')
                cmds.append(f"write_power_profile -stims {stim_alias} {root_str} {levels_str} -unit mW -format fsdb {tcl_args} -out {report_stem}.profile")
            if report.tcl_cmd is not None:
                cmds.append(f"{report.tcl_cmd} -stims {stim_alias} {tcl_args}")

            cfg['report_cmds'] = cmds

            all_power_report_cfgs.append(cfg)
    

        return all_power_report_cfgs


    def report_power(self) -> bool:
        power_cfgs = self.configs_to_cmds()

        block_append = self.block_append
 
        # Fixes issues seen with several different reporting commands
        if "read_db pre_report_power" not in self.output: self.block_append("read_db pre_report_power")

        proc = ["proc dump_frame_info {stim_alias report_stem} {"]
        proc.append("    set frames [get_sdb_frames -stim $stim_alias]")
        proc.append("    set st [open \"${report_stem}.frames.start_times.txt\" w]")
        proc.append("    set et [open \"${report_stem}.frames.end_times.txt\" w]")
        proc.append("    set dt [open \"${report_stem}.frames.duration.txt\" w]")
        proc.append("    foreach frame $frames {puts $st [get_frame_info -frame $frame -start_time]}")
        proc.append("    foreach frame $frames {puts $et [get_frame_info -frame $frame -end_time]}")
        proc.append("    foreach frame $frames {puts $dt [get_frame_info -frame $frame -duration]}")
        proc.append("    close $st; close $et; close $dt")
        proc.append("}")
        self.append('\n'.join(proc))

        for cfg in power_cfgs:
            if 'read_stim_cmd' in cfg:
                block_append(cfg['read_stim_cmd'])
            if 'compute_power_cmd' in cfg:
                block_append(cfg['compute_power_cmd'])
            if 'report_cmds' in cfg:
                for cmd in cfg['report_cmds']:
                    block_append(cmd)
        return True
    
    def parse_power(self) -> bool:
        power_cfgs = self.configs_to_cmds()
        default = dict(interval_ns=None,num_toggles=None,frame_count=None)
        for cfg in power_cfgs:
            if 'report_cmds' not in cfg: continue
            for cmd in cfg['report_cmds']:
                if (' -out ' not in cmd) and (' > ' not in cmd): continue
                fp_in = Path(cmd.split(' -out ')[-1].split(' > ')[-1])
                if not fp_in.is_absolute(): fp_in = Path(self.run_dir)/fp_in
                profile = ('.profile' in fp_in.name)
                if profile:
                    fp_in = fp_in.with_suffix(fp_in.suffix+'.data')
                if not fp_in.exists():
                    self.logger.warning(f"Output file does not exist, {fp_in}")
                    continue
                if profile:
                    func = PowerParser.profiledata_to_df
                # TODO: add more parsing utilities here
                else:
                    self.logger.warning(f"No method to parse report file {fp_in}")
                    continue
                try:
                    dp_out = fp_in.parent/"parsed"
                    dp_out.mkdir(exist_ok=True,parents=True)
                    df = func(fp_in)
                    fp_out = dp_out/(fp_in.name+'.csv.gz')
                    df.to_csv(fp_out,sep=',',compression='gzip')
                    self.logger.info(f"Parsed {fp_in} -> {fp_out}")
                except Exception as e:
                    import inspect
                    self.logger.warning(f"Error with function {func.__name__} parsing output file {fp_in}, fix in {inspect.getfile(func)}")
                    self.logger.warning(str(e))

        return True

    def run_joules(self) -> bool:
        block_append = self.block_append

        """Close out the power script and run Joules"""
        # Quit Joules
        block_append("exit")

        # Create power analysis script
        #   with unique filename so that multiple runs don't overwrite each others' TCL scripts
        now = datetime.now().strftime("%Y%m%d-%H%M%S")
        joules_tcl_filename = os.path.join(self.run_dir, f"joules-{now}.tcl")
        self.write_contents_to_path("\n".join(self.output), joules_tcl_filename)

        # Make sure that generated-scripts exists.
        os.makedirs(self.generated_scripts_dir, exist_ok=True)

        # Create load_power script pointing to latest (symlinked to post_<last ran step>).
        self.output.clear()
        assert self.do_pre_steps(self.first_step)
        self.append("read_db latest")
        self.write_contents_to_path("\n".join(self.output), self.load_power_tcl)

        with open(self.load_power_script, "w") as f:
            f.write(dedent(f"""
        #!/bin/bash
        cd {self.run_dir}
        source enter
        $JOULES_BIN -common_ui -files {self.load_power_tcl}
        """))
        os.chmod(self.load_power_script, 0o755)

        self.create_enter_script()

        # Build args
        args = [
            self.get_setting("power.joules.joules_bin"),
            "-files", joules_tcl_filename,
            "-common_ui",
            "-no_gui",
            "-batch"
        ]

        HammerVLSILogging.enable_colour = False
        HammerVLSILogging.enable_tag = False

<<<<<<< HEAD
       # self.run_executable(args, cwd=self.run_dir)
=======
        output = self.run_executable(args, cwd=self.run_dir)

        self.parse_power()
>>>>>>> 8d32ec3141997550ae0f5aa69d67a5f33711aa90

        HammerVLSILogging.enable_colour = True
        HammerVLSILogging.enable_tag = True

        return True

def joules_global_settings(ht: HammerTool) -> bool:
    """Settings that need to be reapplied at every tool invocation"""
    assert isinstance(ht, HammerPowerTool)
    assert isinstance(ht, CadenceTool)

    max_threads = ht.get_setting("vlsi.core.max_threads")
    ht.block_append(f"set_multi_cpu_usage -local_cpu {max_threads}")
    # use super-threading to parallelize synthesis (up to 8 CPUs)
    ht.block_append("set_db auto_super_thread 1")
    # self.block_append(f"set_db super_thread_servers localhost")
    ht.block_append(f"set_db max_cpus_per_server {max_threads}")
    ht.block_append("set_db max_frame_count 100000000") # default is 1000, too low for most use-cases
    ht.create_enter_script()

    return True


tool = Joules
