/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "watchman/root/warnerr.h"
#include "watchman/Errors.h"
#include "watchman/Logging.h"
#include "watchman/Poison.h"
#include "watchman/root/Root.h"
#include "watchman/watchman_dir.h"

namespace watchman {

void handle_open_errno(
    Root& root,
    watchman_dir* dir,
    std::chrono::system_clock::time_point now,
    const char* syscall,
    const std::error_code& err) {
  auto dir_name = dir->getFullPath();
  bool log_warning = true;

  if (err == error_code::no_such_file_or_directory ||
      err == error_code::not_a_directory ||
      err == error_code::too_many_symbolic_link_levels) {
    log_warning = false;
  } else if (err == error_code::permission_denied) {
    log_warning = true;
  } else if (err == error_code::system_limits_exceeded) {
    set_poison_state(dir_name, now, syscall, err);
    if (!root.failure_reason) {
      root.failure_reason = w_string::build(*poisoned_reason.rlock());
    }
    return;
  } else {
    log_warning = true;
  }

  if (w_string_equal(dir_name, root.root_path)) {
    auto warn = w_string::build(
        syscall,
        "(",
        dir_name,
        ") -> ",
        err.message(),
        ". Root is inaccessible; cancelling watch\n");
    log(ERR, warn);
    if (!root.failure_reason) {
      root.failure_reason = warn;
    }
    root.cancel();
    return;
  }

  auto warn = w_string::build(
      syscall,
      "(",
      dir_name,
      ") -> ",
      err.message(),
      ". Marking this portion of the tree deleted");

  log(err == error_code::no_such_file_or_directory ? DBG : ERR, warn, "\n");
  if (log_warning) {
    root.recrawlInfo.wlock()->warning = warn;
  }
}

} // namespace watchman
