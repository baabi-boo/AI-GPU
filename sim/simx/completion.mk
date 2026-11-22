# SPDX-License-Identifier: Apache-2.0
include Makefile

SIMX_COMPLETION_TEST_SUFFIX := $(if $(filter 1,$(COMPLETION_TEST_LEGACY)),_legacy)
SIMX_COMPLETION_TEST_OBJ := $(OBJ_DIR)/tests/simx_completion_test$(SIMX_COMPLETION_TEST_SUFFIX).o
SIMX_COMPLETION_TEST := $(DESTDIR)/simx_completion_test$(SIMX_COMPLETION_TEST_SUFFIX)
COMPLETION_TEST_FLAGS := $(if $(filter 1,$(COMPLETION_TEST_LEGACY)),-DSIMX_COMPLETION_USE_LEGACY_RUN)

.PHONY: test-completion clean-completion

test-completion: $(SIMX_COMPLETION_TEST)
	$(SIMX_COMPLETION_TEST)

$(SIMX_COMPLETION_TEST_OBJ): $(VORTEX_HOME)/tests/unittest/simx_completion/main.cpp $(CONFIG_FILE)
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) $(COMPLETION_TEST_FLAGS) -c $< -o $@

$(SIMX_COMPLETION_TEST): $(OBJS) $(SIMX_COMPLETION_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ $(LDFLAGS) -pthread -o $@

-include $(SIMX_COMPLETION_TEST_OBJ:.o=.d)

clean-exe: clean-completion
clean-completion:
	rm -f $(SIMX_COMPLETION_TEST)
